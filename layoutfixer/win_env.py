"""The real Windows environment for the engine."""

from __future__ import annotations

import logging
import time

from .clipboard import Win32Clipboard
from .config import Settings
from .paste import ClipboardPaster
from .targets.base import TextTarget, Unsupported
from .targets.clipboard_target import ClipboardSelectionTarget
from .targets.native_edit import NativeEditTarget, is_native_edit_class
from .targets.uia_target import UiaTarget
from .uia import UIA_DocumentControlTypeId, UIA_EditControlTypeId, UiaClient
from .win import focus as wfocus
from .win import layouts
from .win.keyboard import Keyboard

log = logging.getLogger(__name__)

TERMINAL_PROCESSES = {"windowsterminal.exe", "openconsole.exe", "conhost.exe", "wt.exe", "cmd.exe",
                      "powershell.exe", "pwsh.exe", "mintty.exe", "putty.exe", "kitty.exe", "alacritty.exe",
                      "wezterm-gui.exe", "conemu.exe", "conemu64.exe", "tabby.exe", "hyper.exe"}
TERMINAL_CLASSES = {"consolewindowclass", "cascadia_hosting_window_class", "pseudoconsolewindow", "putty",
                    "mintty", "virtualconsoleclass"}

UIA_SETTLE_S = 1.0  # how long a Chromium-based app gets to expose the focused field
UIA_RETRY_S = 0.15

UNSUPPORTED_MESSAGE = ("Layout Fixer can't read the text in this window. Select the text and try again, "
                       "or use a different app")


def is_terminal(f: wfocus.FocusInfo) -> bool:
    return f.process_name in TERMINAL_PROCESSES or f.class_name.lower() in TERMINAL_CLASSES


class WindowsEnvironment:
    """Must be used from one thread (the dispatcher's worker): UI Automation objects are per thread."""

    def __init__(self):
        self.keyboard = Keyboard()
        self.clipboard = Win32Clipboard()
        self._uia: UiaClient | None = None
        self._uia_failed = False

    def uia(self) -> UiaClient | None:
        if self._uia is None and not self._uia_failed:
            try:
                self._uia = UiaClient()
            except Exception:
                log.exception("UI Automation unavailable")
                self._uia_failed = True
        return self._uia

    def focus(self) -> wfocus.FocusInfo | None:
        return wfocus.get_focus()

    def is_blocked(self, f: wfocus.FocusInfo) -> bool:
        return wfocus.is_more_privileged(f.pid)

    def current_lang(self, f: wfocus.FocusInfo) -> str | None:
        return layouts.lang_of(layouts.thread_layout(f.thread_id))

    def switch_layout(self, f: wfocus.FocusInfo, lang: str) -> layouts.SwitchResult:
        return layouts.switch_layout(f.hwnd_focus, f.hwnd_top, f.thread_id, lang)

    def make_target(self, f: wfocus.FocusInfo, settings: Settings) -> TextTarget:
        if is_terminal(f):
            raise Unsupported("Terminal windows are not supported")
        if f.hwnd_focus and is_native_edit_class(f.class_name):
            return NativeEditTarget(f.hwnd_focus, f.class_name)
        control_type = None
        client = self.uia()
        if client is not None:
            target, control_type = self._uia_target(client, f)
            if target is not None:
                return target
        textish = f.has_caret or control_type in (UIA_EditControlTypeId, UIA_DocumentControlTypeId)
        log.info("no readable text field (caret=%s, control type=%s, clipboard fallback=%s)", f.has_caret,
                 control_type, settings.clipboard_fallback)
        if settings.clipboard_fallback and textish:
            return ClipboardSelectionTarget(self.clipboard, self.keyboard,
                                            wait_idle=lambda: wfocus.wait_responsive(f.target_hwnd))
        raise Unsupported(UNSUPPORTED_MESSAGE)

    def _uia_target(self, client: UiaClient, f: wfocus.FocusInfo) -> tuple[UiaTarget | None, int | None]:
        """The focused element as a UiaTarget, or (None, its control type) when it is not a text field.

        Chromium-based apps (Chrome, Edge, Electron apps) build their accessibility tree only after a
        UI Automation client first asks for it, so the first answer is often just the window pane.
        The focused element is asked for again for up to UIA_SETTLE_S before giving up.
        """
        idle = lambda: wfocus.wait_responsive(f.target_hwnd)  # noqa: E731
        deadline = time.monotonic() + UIA_SETTLE_S
        attempt = 0
        control_type = None
        while True:
            attempt += 1
            el = client.focused_element()
            if el is not None:
                target = UiaTarget(client, el, ClipboardPaster(self.clipboard, self.keyboard, wait_idle=idle))
                try:
                    target.check_editable()  # password / read-only / disabled: TargetError, stops here
                    log.info("UI Automation: text field found (control type %s, attempt %d)",
                             target.control_type, attempt)
                    return target, target.control_type
                except Unsupported as e:
                    try:
                        control_type = el.CurrentControlType
                        cls = el.CurrentClassName
                    except Exception:
                        control_type, cls = None, "?"
                    log.info("UI Automation attempt %d: %s (control type %s, class %s)", attempt, e,
                             control_type, cls)
            else:
                log.info("UI Automation attempt %d: no focused element", attempt)
            if time.monotonic() >= deadline or wfocus.get_focus() != f:
                return None, control_type
            time.sleep(UIA_RETRY_S)
