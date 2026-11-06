"""Mac parts of the Settings window: shortcut recording through the event tap, permission and Fn hints.

Qt never reports the Fn key, so shortcuts are recorded by the event tap
(mac/hotkeys.py) instead of the widget's own key events.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit

from ..hotkeys import HotkeyError


class MacSupport:
    """What the Settings window needs from the Mac platform (all injectable for tests)."""

    def __init__(self, recorder, trusted: Callable[[], bool], open_accessibility: Callable[[], None],
                 fn_key_action: Callable[[], str | None], open_keyboard: Callable[[], None]):
        self.recorder = recorder
        self.trusted = trusted
        self.open_accessibility = open_accessibility
        self.fn_key_action = fn_key_action
        self.open_keyboard = open_keyboard


class MacHotkeyEdit(QLineEdit):
    """Click, then press the new shortcut (e.g. hold Cmd and Fn, then let go). Escape stops recording;
    Delete clears it (when ``allow_empty``)."""

    recording = Signal(bool)
    _recorded = Signal(object)

    def __init__(self, text: str = "", recorder=None, allow_empty: bool = False, parent=None):
        super().__init__(text, parent)
        self.recorder = recorder
        self.allow_empty = allow_empty
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setPlaceholderText("Not set - click and press keys" if allow_empty else "Click and press keys")
        self.error = ""
        self._recorded.connect(self._on_recorded, Qt.ConnectionType.QueuedConnection)

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self.recording.emit(True)
        if self.recorder is None or not self.recorder.start_recording(self._recorded.emit):
            self.error = "Turn on the Accessibility permission first - shortcuts can't be recorded without it"
            self.setToolTip(self.error)

    def focusOutEvent(self, e) -> None:
        if self.recorder is not None:
            self.recorder.stop_recording()
        super().focusOutEvent(e)
        self.recording.emit(False)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:  # also reaches us when the event tap is not running
            self.clearFocus()

    def _on_recorded(self, result) -> None:
        if result == "cancel":
            self.clearFocus()
        elif result == "clear":
            if self.allow_empty:
                self.setText("")
                self.error = ""
        elif isinstance(result, HotkeyError):
            self.error = str(result)
            self.setToolTip(self.error)
        else:
            self.error = ""
            self.setToolTip("")
            self.setText(str(result))
            self.clearFocus()
