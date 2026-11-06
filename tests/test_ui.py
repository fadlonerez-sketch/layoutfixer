"""Qt UI on the offscreen platform: settings window, shortcut recorder, toast, tray app wiring.

Key events here are Qt-level events delivered to our own widget, not OS input.
"""

import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from fakes import FakeEnv, FakeTarget
from layoutfixer.config import Settings
from layoutfixer.hotkeys import HotkeyStatus
from layoutfixer.ui.settings_window import HotkeyEdit, SettingsWindow
from layoutfixer.ui.toast import Toast

RARE = "Ctrl+Alt+Shift+F21"


def key(widget, vk, qt_key, mods=Qt.KeyboardModifier.NoModifier):
    ev = QKeyEvent(QEvent.Type.KeyPress, qt_key, mods, 0, vk, 0)
    widget.keyPressEvent(ev)


def test_hotkey_edit_records_combo(qtbot):
    e = HotkeyEdit("Ctrl+Space")
    qtbot.addWidget(e)
    key(e, 0x20, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert e.text() == "Ctrl+Shift+Space"
    key(e, 0x41, Qt.Key.Key_A)  # plain letter is refused
    assert e.text() == "Ctrl+Shift+Space" and e.error
    key(e, 0x11, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)  # modifier alone: ignored
    assert e.text() == "Ctrl+Shift+Space"


def test_hotkey_edit_clear(qtbot):
    e = HotkeyEdit("Ctrl+Q", allow_empty=True)
    qtbot.addWidget(e)
    key(e, 0x08, Qt.Key.Key_Backspace)
    assert e.text() == ""


def test_settings_window_saves(qtbot):
    saved = []
    w = SettingsWindow(Settings(), HotkeyStatus(True), lambda: "Hebrew keyboard: installed")
    qtbot.addWidget(w)
    w.saved.connect(saved.append)
    w.notify.setChecked(False)
    w.to_he.setText("Ctrl+Alt+Shift+H")
    w._save()
    assert saved and saved[0].notify_success is False and saved[0].to_hebrew_hotkey == "Ctrl+Alt+Shift+H"


def test_settings_window_rejects_bad_shortcut(qtbot):
    saved = []
    w = SettingsWindow(Settings(), HotkeyStatus(True), lambda: "")
    qtbot.addWidget(w)
    w.saved.connect(saved.append)
    w.hotkey.setText("Shift+A")
    w._save()
    assert not saved and "typing" in w.message.text()


def test_toast_never_takes_focus(qtbot):
    t = Toast()
    qtbot.addWidget(t)
    flags = t.windowFlags()
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowType.WindowTransparentForInput
    assert t.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    t.show_message("Converted to Hebrew", "success", 50)
    assert t.isVisible() and t.last_message == "Converted to Hebrew"
    qtbot.waitUntil(lambda: not t.isVisible(), timeout=2000)


@pytest.fixture
def tray_app(qtbot, monkeypatch, qapp):
    from layoutfixer import app as app_mod
    monkeypatch.setattr(app_mod.startup, "is_enabled", lambda *a: False)
    monkeypatch.setattr(app_mod.startup, "points_here", lambda *a: True)
    monkeypatch.setattr(app_mod.startup, "set_enabled", lambda *a, **k: None)
    env = FakeEnv(target=FakeTarget("akuo"))
    a = app_mod.LayoutFixerApp(qapp, Settings(hotkey=RARE, fallback_hotkey=""), first_run=False, env=env)
    yield a, env
    a.hotkey_thread.stop()
    a.dispatcher.stop()
    a.tray.hide()
    a.toast.hide()
    if a.settings_window:
        a.settings_window.close()


def test_app_registers_and_converts_on_hotkey(tray_app, qtbot):
    a, env = tray_app
    assert a.hotkeys.status.active and str(a.hotkeys.status.convert.hotkey) == RARE
    a._on_hotkey("convert")  # what the hotkey thread calls on WM_HOTKEY
    qtbot.waitUntil(lambda: a.toast.last_message.startswith("Converted"), timeout=3000)
    assert env.target.text == "שלום" and a.toast.last_level == "success"


def test_disable_releases_shortcut(tray_app, qtbot):
    a, env = tray_app
    a.set_enabled(False)
    assert a.hotkey_thread.registered() == {}
    a._on_hotkey("convert")
    time.sleep(0.2)
    assert env.target.text == "akuo"
    a.set_enabled(True)
    assert a.hotkey_thread.registered()


def test_recording_suspends_shortcuts(tray_app):
    a, _ = tray_app
    a._recording(True)
    assert a.hotkey_thread.registered() == {}
    a._recording(False)
    assert "convert" in a.hotkey_thread.registered()


def test_success_notification_can_be_turned_off(tray_app, qtbot):
    a, env = tray_app
    a.settings = Settings(hotkey=RARE, fallback_hotkey="", notify_success=False)
    a.toast.last_message = ""
    a._on_hotkey("convert")
    qtbot.waitUntil(lambda: env.target.text == "שלום", timeout=3000)
    time.sleep(0.1)
    qtbot.wait(50)
    assert a.toast.last_message == ""
