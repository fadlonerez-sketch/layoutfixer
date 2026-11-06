"""Tray application: wires hotkeys -> dispatcher -> engine -> notification."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__
from .config import IS_MAC, Settings, data_dir
from .converter import Direction
from .engine import Dispatcher, Engine, Outcome
from .hotkeys import HotkeyManager, HotkeyStatus, HotkeyThread
from .ui.icon import app_icon
from .ui.settings_window import SettingsWindow
from .ui.toast import Toast

if IS_MAC:
    from .mac import startup
else:
    from . import startup

log = logging.getLogger("layoutfixer")

# "convert_alt": the Mac's alternative shortcut, active together with the main one
ACTIONS = {"convert": None, "convert_alt": None, "to_hebrew": Direction.EN_TO_HE, "to_english": Direction.HE_TO_EN}


def setup_logging() -> None:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs / "layoutfixer.log", maxBytes=512_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def layouts_info() -> str:
    if IS_MAC:
        return mac_layouts_info()
    from .win import layouts
    he, en = layouts.find_layout("he"), layouts.find_layout("en")
    parts = [f"Hebrew keyboard: {'installed' if he else '<b>missing</b>'}",
             f"English keyboard: {'installed' if en else '<b>missing</b>'}"]
    text = " &nbsp;·&nbsp; ".join(parts)
    if not (he and en):
        text += ("<br>Add the missing language in Windows Settings &gt; Time &amp; language &gt; Language "
                 "so the keyboard can be switched after converting.")
    return text


def mac_layouts_info() -> str:
    from .mac import tis
    from .mac.layouts import pick_layout
    try:
        enabled = tis.list_sources(False)
    except Exception:
        log.exception("could not list the input sources")
        return ""
    he, en = pick_layout(enabled, "he"), pick_layout(enabled, "en")
    parts = [f"Hebrew keyboard: {he.name if he else '<b>not added</b>'}",
             f"English keyboard: {en.name if en else '<b>not added</b>'}"]
    text = " &nbsp;·&nbsp; ".join(parts)
    if not (he and en):
        text += ("<br>Add the missing one in System Settings &gt; Keyboard &gt; Text Input &gt; Input Sources "
                 "&gt; Edit so the keyboard can be switched after converting.")
    return text


class LayoutFixerApp(QObject):
    outcome_ready = Signal(object)
    tap_state_changed = Signal(bool)  # macOS: the event tap started (the Accessibility permission was granted)

    def __init__(self, qapp: QApplication, settings: Settings, first_run: bool, env=None,
                 announce: bool = True):
        super().__init__()
        self.qapp = qapp
        self.settings = settings
        self.mac_support = None
        if IS_MAC:
            from .mac import permissions
            from .mac.hotkeys import MacHotkeyManager, MacHotkeyThread
            from .mac.ui import MacSupport
            from .mainthread import MainThreadRunner
            self.main_runner = MainThreadRunner()
            if env is None:
                from .mac.env import MacEnvironment
                env = MacEnvironment(self.main_runner.call, self.main_runner.post)
            self.hotkey_thread = MacHotkeyThread(self._on_hotkey, on_armed=self._on_armed,
                                                 on_state=self.tap_state_changed.emit, trusted=permissions.is_trusted)
            self.hotkeys = MacHotkeyManager(self.hotkey_thread)
            self.tap_state_changed.connect(self._tap_state, Qt.ConnectionType.QueuedConnection)
            self.mac_support = MacSupport(
                self.hotkey_thread, permissions.is_trusted, lambda: permissions.open_settings(),
                permissions.fn_key_action, lambda: permissions.open_settings(permissions.KEYBOARD_URL))
        elif env is None:
            from .win_env import WindowsEnvironment
            env = WindowsEnvironment()
        self.engine = Engine(env, lambda: self.settings)
        self.outcome_ready.connect(self._show_outcome, Qt.ConnectionType.QueuedConnection)
        self.dispatcher = Dispatcher(self.engine.run, self.outcome_ready.emit,
                                     cooldown_s=lambda: self.settings.cooldown_ms / 1000)
        if not IS_MAC:
            self.hotkey_thread = HotkeyThread(self._on_hotkey)
            self.hotkeys = HotkeyManager(self.hotkey_thread)
        self.toast = Toast()
        self.settings_window: SettingsWindow | None = None

        self.tray = QSystemTrayIcon(app_icon(settings.enabled), self)
        menu = QMenu()
        self.enabled_action = QAction("Enabled", menu, checkable=True)
        self.enabled_action.setChecked(settings.enabled)
        self.enabled_action.toggled.connect(self.set_enabled)
        menu.addAction(self.enabled_action)
        menu.addAction("Settings...", self.show_settings)
        menu.addAction("Open log folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(data_dir() / "logs"))))
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        status = self.apply_settings(settings, save=False, announce=announce or first_run)
        if not (announce or first_run) and settings.enabled and (not status.active or status.fallback_used):
            self._announce(status)  # shortcut problems are shown even when started in the background
        if first_run or not status.active and settings.enabled:
            QTimer.singleShot(300, self.show_settings)

    # ------------------------------------------------------------------ settings
    def apply_settings(self, settings: Settings, save: bool = True, announce: bool = False) -> HotkeyStatus:
        if save and settings.start_at_login != startup.is_enabled():
            try:
                startup.set_enabled(settings.start_at_login)
            except OSError as e:
                log.warning("could not change start-at-login: %s", e)
                settings = replace(settings, start_at_login=startup.is_enabled())
        elif settings.start_at_login and not startup.points_here():
            try:
                startup.set_enabled(True)  # the app was moved: point the Run entry at this copy
            except OSError:
                pass
        self.settings = settings
        if save:
            try:
                settings.save()
            except OSError as e:
                log.error("could not save settings: %s", e)
                self.toast.show_message(f"Could not save settings: {e}", "error")
        status = self.hotkeys.apply(settings)
        self.enabled_action.blockSignals(True)
        self.enabled_action.setChecked(settings.enabled)
        self.enabled_action.blockSignals(False)
        self.tray.setIcon(app_icon(settings.enabled and status.active))
        self.tray.setToolTip(f"Layout Fixer {__version__}\n{status.summary()}"[:127])
        if self.settings_window is not None:
            self.settings_window.show_status(status)
        if announce or save:
            self._announce(status)
        return status

    def _announce(self, status: HotkeyStatus) -> None:
        if not status.enabled:
            self.toast.show_message("Layout Fixer is disabled", "info", 2500)
        elif not status.active and IS_MAC and any("Accessibility" in e for e in status.errors):
            self.toast.show_message("Layout Fixer needs the Accessibility permission: System Settings > Privacy & "
                                    "Security > Accessibility > turn on Layout Fixer. The shortcut starts working "
                                    "a few seconds later.", "error", 15000)
        elif not status.active:
            self.toast.show_message("Layout Fixer could not register a shortcut: " + "; ".join(status.errors)
                                    + ". Choose another one in Settings.", "error", 8000)
        elif status.fallback_used:
            self.toast.show_message(f"{self.settings.hotkey} is taken by another program - using "
                                    f"{status.convert.hotkey} instead", "warning", 6000)  # type: ignore[union-attr]
        else:
            msg = f"Layout Fixer is running - press {status.convert.hotkey} in a text field"  # type: ignore[union-attr]
            if status.errors:
                self.toast.show_message(msg + ". " + "; ".join(status.errors), "warning", 6000)
            else:
                self.toast.show_message(msg, "info", 3000)

    def set_enabled(self, enabled: bool) -> None:
        self.apply_settings(replace(self.settings, enabled=enabled))

    def show_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.settings, self.hotkeys.status, layouts_info, self.mac_support)
            self.settings_window.saved.connect(self.apply_settings)
            self.settings_window.recording.connect(self._recording)
        else:
            self.settings_window.load(self.settings, self.hotkeys.status)
        self.settings_window.show()
        self.settings_window.raise_()
        if IS_MAC:
            _activate_mac_app()  # a menu-bar app is not active by itself; bring the window to the front
        self.settings_window.activateWindow()

    def _recording(self, active: bool) -> None:
        # Our own registration would swallow the keys the user is trying to record.
        if active:
            self.hotkeys.suspend()
        else:
            self.hotkeys.apply(self.settings)

    def _tray_activated(self, reason) -> None:
        if IS_MAC:
            return  # a click on a menu-bar icon opens its menu (Settings is in it)
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_settings()

    # ------------------------------------------------------------------ conversions
    def _on_hotkey(self, name: str) -> None:  # hotkey thread
        log.info("hotkey pressed: %s (enabled=%s)", name, self.settings.enabled)
        if self.settings.enabled and name in ACTIONS:
            self.dispatcher.trigger(ACTIONS[name])

    def _on_armed(self, name: str) -> None:  # event tap thread (macOS)
        if self.settings.enabled and name in ACTIONS:
            note = getattr(self.engine.env, "note_chord_armed", None)
            if note is not None:
                note()

    def _tap_state(self, active: bool) -> None:  # macOS, Qt thread
        log.info("event tap state: active=%s", active)
        self.apply_settings(self.settings, save=False, announce=True)

    def _show_outcome(self, outcome: Outcome) -> None:
        log.info("outcome: ok=%s level=%s strategy=%s message=%r", outcome.ok, outcome.level, outcome.strategy,
                 outcome.message)  # messages are fixed texts, never field contents
        if outcome.level == "silent":
            return
        if outcome.level == "success" and not self.settings.notify_success:
            return
        self.toast.show_message(outcome.message, outcome.level)

    def quit(self) -> None:
        self.hotkey_thread.stop()
        self.dispatcher.stop(timeout=10)  # let a running conversion restore the clipboard
        self.tray.hide()
        self.qapp.quit()


SERVER_NAME = "LayoutFixer-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")


def _activate_mac_app() -> None:
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        log.exception("could not activate the app")


def _already_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="LayoutFixer")
    parser.add_argument("--background", action="store_true", help="start without the welcome notification")
    parser.add_argument("--selftest", metavar="REPORT", help="run the self-test, write a JSON report, exit")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.selftest:
        if IS_MAC:
            from .mac.selftest import run_selftest
        else:
            from .selftest import run_selftest
        return run_selftest(args.selftest)

    setup_logging()
    QApplication.setQuitOnLastWindowClosed(False)
    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName("Layout Fixer")
    qapp.setWindowIcon(app_icon())
    if _already_running():
        return 0
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    settings_path = data_dir() / "settings.json"
    first_run = not settings_path.exists()
    settings = Settings.load()
    settings.start_at_login = startup.is_enabled()
    if first_run:
        try:
            settings.save()
        except OSError:
            pass
    log.info("Layout Fixer %s starting (frozen=%s, platform=%s)", __version__, getattr(sys, "frozen", False),
             sys.platform)
    if IS_MAC:
        from .mac import permissions
        if not permissions.is_trusted(prompt=True):  # macOS shows its own "allow Accessibility" dialog
            log.info("Accessibility permission not granted yet")
            first_run = True  # open Settings: it explains the permission
    app = LayoutFixerApp(qapp, settings, first_run, announce=not args.background)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), app.show_settings()))

    server.newConnection.connect(on_connection)
    code = qapp.exec()
    log.info("Layout Fixer stopped")
    return code
