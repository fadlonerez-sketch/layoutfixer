"""Last resort for controls that expose nothing (no Win32 edit, no UI Automation text).

Selection only: Ctrl+C copies what the user selected, the conversion is pasted
over it with Ctrl+V, and the original clipboard is restored afterwards. With
nothing selected there is no safe way to know the field's extent, so it stops.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from ..clipboard import ClipboardBackend, ClipboardGuard
from ..paste import clipboard_note
from .base import FieldState, ReplaceResult, TargetError, TextTarget

log = logging.getLogger(__name__)

NO_SELECTION = "Nothing is selected. In this app, select the text first, then press the shortcut"


class ClipboardSelectionTarget(TextTarget):
    kind = "clipboard"

    def __init__(self, backend: ClipboardBackend, keyboard, copy_timeout_s: float = 0.6,
                 paste_delay_s: float = 0.6, sleep: Callable[[float], None] = time.sleep,
                 wait_idle: Callable[[], bool] = lambda: True, late_copy_grace_s: float = 0.4):
        self.backend = backend
        self.keyboard = keyboard
        self.copy_timeout_s = copy_timeout_s
        self.paste_delay_s = paste_delay_s
        self.sleep = sleep
        self.wait_idle = wait_idle
        self.late_copy_grace_s = late_copy_grace_s
        self.guard: ClipboardGuard | None = None
        self._copy_sent = False

    def read(self) -> FieldState:
        self.guard = ClipboardGuard(self.backend).__enter__()
        before = self.backend.sequence()
        self._copy_sent = True  # even a partly accepted Ctrl+C may make the app write the clipboard
        sent = self.keyboard.copy()
        deadline = time.monotonic() + self.copy_timeout_s
        while sent and self.backend.sequence() == before and time.monotonic() < deadline:
            self.sleep(0.02)
        if self.backend.sequence() != before:
            self.sleep(0.03)  # let the app finish writing all its formats
            self.guard.mark_ours()  # whatever our Ctrl+C put there gets replaced by the backup later
        if not sent:
            raise TargetError("Windows did not accept the copy keystroke")
        if self.backend.sequence() == before:
            raise TargetError(NO_SELECTION)
        text = self.backend.get_text()
        if not text:
            raise TargetError(NO_SELECTION)
        if text.endswith("\n") and text.count("\n") == 1 and len(text) > 1:
            # Editors such as VS Code copy the whole line when nothing is selected.
            raise TargetError(NO_SELECTION)
        return FieldState(text, 0, len(text), selection_only=True)

    def replace(self, state: FieldState, start: int, end: int, new_text: str) -> ReplaceResult:
        assert self.guard is not None
        self.guard.set_text(new_text)
        if not self.keyboard.paste():
            raise TargetError("Windows did not accept the paste keystroke; nothing was changed")
        self.sleep(self.paste_delay_s)  # cannot read this control back; give the app time to paste
        if not self.wait_idle():
            self.guard.abandon("target not responding")
        self.guard.restore()
        notes = [n for n in (clipboard_note(self.guard), "pasted (this app cannot be read back to verify)") if n]
        return ReplaceResult(False, "; ".join(notes))

    def close(self) -> None:
        guard = self.guard
        if guard is None:
            return
        self.guard = None
        if self._copy_sent and not guard.changed and not guard.restored:
            # Our Ctrl+C may still be on its way (slow app): give it a moment, and if the clipboard
            # changed since the backup, treat that change as ours so the backup goes back.
            self.sleep(self.late_copy_grace_s)
            if self.backend.sequence() != guard.baseline:
                guard.mark_ours()
        if not guard.restore():
            log.warning("clipboard fallback: the user's clipboard could not be restored")
