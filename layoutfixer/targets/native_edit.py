"""Standard Win32 Edit and RichEdit controls, driven with their own messages.

No clipboard and no keystrokes: WM_GETTEXT / EM_GETSEL to read, EM_SETSEL +
EM_REPLACESEL (undoable, so Ctrl+Z in the app reverts it) to change only the
characters that differ, then the text is read back and compared. If it does not
match, the change is undone with EM_UNDO. Windows marshals these messages
across processes because they are below WM_USER.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes as W

from ..textindex import from_units, normalize_newlines, to_units
from ..win import api
from .base import FieldState, ReplaceResult, TargetError, TextTarget

log = logging.getLogger(__name__)

NATIVE_EXACT = {"edit", "tedit", "tmemo", "tmaskedit", "thunderrt6textbox", "thundertextbox"}


def is_native_edit_class(class_name: str) -> bool:
    c = class_name.lower()
    return c in NATIVE_EXACT or c.startswith("windowsforms10.edit") or "richedit" in c


class NativeEditTarget(TextTarget):
    kind = "native"

    def __init__(self, hwnd: int, class_name: str, timeout_ms: int = 1500):
        self.hwnd = hwnd
        self.rich = "richedit" in class_name.lower()
        self.timeout_ms = timeout_ms

    def _send(self, msg: int, wparam: int = 0, lparam: int = 0) -> int:
        r = api.send_message_timeout(self.hwnd, msg, wparam, lparam, self.timeout_ms)
        if r is None:
            raise TargetError("The application is not responding")
        return r

    def _text(self) -> str:
        n = self._send(api.WM_GETTEXTLENGTH)
        buf = ctypes.create_unicode_buffer(n + 2)
        copied = self._send(api.WM_GETTEXT, n + 2, ctypes.addressof(buf))
        return ctypes.wstring_at(ctypes.addressof(buf), min(copied, n + 1))

    def _selection_units(self) -> tuple[int, int]:
        start, end = W.DWORD(0xFFFFFFFF), W.DWORD(0xFFFFFFFF)
        packed = self._send(api.EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end))
        if start.value != 0xFFFFFFFF and end.value != 0xFFFFFFFF:
            return start.value, end.value
        # Pointer form not marshalled: fall back to the packed 16-bit return value.
        return packed & 0xFFFF, (packed >> 16) & 0xFFFF

    def read(self) -> FieldState:
        if not api.IsWindow(self.hwnd):
            raise TargetError("The text field went away")
        style = api.GetWindowLongPtrW(self.hwnd, api.GWL_STYLE)
        if style & api.ES_PASSWORD:
            raise TargetError("Password fields are not changed")
        if style & api.ES_READONLY or not api.IsWindowEnabled(self.hwnd):
            raise TargetError("This text field is read-only")
        text = self._text()
        su, eu = self._selection_units()
        start = from_units(text, su, self.rich)
        end = from_units(text, eu, self.rich)
        if start > end:
            start, end = end, start
        return FieldState(text, start, end)

    def replace(self, state: FieldState, start: int, end: int, new_text: str) -> ReplaceResult:
        if self._text() != state.text:
            raise TargetError("The text changed while converting; nothing was replaced")
        u0, u1 = to_units(state.text, start, self.rich), to_units(state.text, end, self.rich)
        self._send(api.EM_SETSEL, u0, u1)
        buf = ctypes.create_unicode_buffer(new_text[start:end])
        self._send(api.EM_REPLACESEL, 1, ctypes.addressof(buf))
        after = self._text()
        if after != new_text and normalize_newlines(after) != normalize_newlines(new_text):
            if after == state.text:
                # Nothing happened - EM_UNDO now would undo the user's own last edit instead.
                raise TargetError("The field did not accept the change; nothing was changed")
            self._send(api.EM_UNDO)
            undone = self._text() == state.text
            log.warning("native replace verification failed (undone=%s)", undone)
            if undone:
                raise TargetError("The field did not accept the change; it was undone")
            raise TargetError("The field did not accept the change as expected - press Ctrl+Z to undo",
                              changed=True)
        # Same length text, so the user's caret / selection goes back exactly where it was.
        self._send(api.EM_SETSEL, to_units(after, state.sel_start, self.rich),
                   to_units(after, state.sel_end, self.rich))
        self._send(api.EM_SCROLLCARET)
        return ReplaceResult(True)
