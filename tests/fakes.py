"""Test doubles. Input and the clipboard are always faked (tests never touch the real ones)."""

from __future__ import annotations

from dataclasses import dataclass, field

from layoutfixer.clipboard import Snapshot
from layoutfixer.targets.base import FieldState, ReplaceResult, TargetError, TextTarget
from layoutfixer.win.focus import FocusInfo
from layoutfixer.win.layouts import SwitchResult


class FakeClipboard:
    """In-memory clipboard with Windows-like sequence numbers."""

    def __init__(self, formats: dict[int, bytes] | None = None):
        self.formats: dict[int, bytes] = dict(formats or {})
        self.seq = 1
        self.history: list[str] = []  # every text we were asked to put on it
        self.fail_set = False
        self.restores = 0
        self.busy_restores = 0  # next N restores find the clipboard held open

    def _bump(self):
        self.seq += 1

    def sequence(self) -> int:
        return self.seq

    def snapshot(self) -> Snapshot:
        return Snapshot(items=[(f, "bytes", d) for f, d in self.formats.items()])

    def restore(self, snap: Snapshot, expected_seq: int | None = None) -> str:
        if self.busy_restores:
            self.busy_restores -= 1
            from layoutfixer.clipboard import ClipboardError
            raise ClipboardError("the clipboard is in use by another program")
        if expected_seq is not None and self.seq != expected_seq:
            return "changed"
        self.formats = {f: d for f, _k, d in snap.items}
        self.restores += 1
        self._bump()
        return "restored"

    def discard(self, snap: Snapshot) -> None:
        pass

    def set_text(self, text: str) -> bool:
        if self.fail_set:
            self.formats = {}  # like Win32: EmptyClipboard ran, SetClipboardData failed
            self._bump()
            return False
        self.formats = {13: (text + "\0").encode("utf-16-le")}
        self.history.append(text)
        self._bump()
        return True

    def get_text(self) -> str | None:
        data = self.formats.get(13)
        return data.decode("utf-16-le").rstrip("\0") if data is not None else None

    def external_copy(self, text: str) -> None:
        """Another program (or the user) copies something."""
        self.formats = {13: (text + "\0").encode("utf-16-le")}
        self._bump()


class FakeKeyboard:
    """Records keystrokes; ``on_paste`` / ``on_copy`` simulate what the target app would do."""

    def __init__(self, released: bool = True):
        self.released = released
        self.events: list[str] = []
        self.on_paste = None
        self.on_copy = None
        self.accept = True

    def wait_for_release(self) -> bool:
        return self.released

    def copy(self) -> bool:
        self.events.append("ctrl+c")
        if self.on_copy:
            self.on_copy()
        return self.accept

    def paste(self) -> bool:
        self.events.append("ctrl+v")
        if self.on_paste and self.accept:
            self.on_paste()
        return self.accept


class FakeTarget(TextTarget):
    """A text field held in memory."""

    kind = "fake"

    def __init__(self, text: str, sel: tuple[int, int] | None = None, fail_replace: Exception | None = None):
        self.text = text
        self.sel = sel or (len(text), len(text))
        self.fail_replace = fail_replace
        self.closed = False
        self.replaced: list[tuple[int, int, str]] = []

    def read(self) -> FieldState:
        return FieldState(self.text, *self.sel)

    def replace(self, state: FieldState, start: int, end: int, new_text: str) -> ReplaceResult:
        if self.fail_replace:
            raise self.fail_replace
        assert new_text[:start] == state.text[:start] and new_text[end:] == state.text[end:]
        self.replaced.append((start, end, new_text[start:end]))
        self.text = self.text[:start] + new_text[start:end] + self.text[end:]
        return ReplaceResult(True)

    def close(self) -> None:
        self.closed = True


def focus(pid: int = 4242, class_name: str = "Chrome_WidgetWin_1", process: str = "app.exe") -> FocusInfo:
    return FocusInfo(hwnd_top=100, hwnd_focus=101, thread_id=7, pid=pid, class_name=class_name,
                     process_name=process, has_caret=True)


@dataclass
class FakeEnv:
    target: TextTarget | None = None
    lang: str | None = "en"
    blocked: bool = False
    focus_info: FocusInfo | None = field(default_factory=focus)
    keyboard: FakeKeyboard = field(default_factory=FakeKeyboard)
    switch_ok: bool = True
    switched: list[str] = field(default_factory=list)
    make_error: Exception | None = None

    def focus(self):
        return self.focus_info

    def is_blocked(self, f):
        return self.blocked

    def current_lang(self, f):
        return self.lang

    def switch_layout(self, f, lang):
        self.switched.append(lang)
        if self.switch_ok:
            self.lang = lang
            return SwitchResult(True, "switched", None, lang)
        return SwitchResult(False, "the window ignored the request")

    def make_target(self, f, settings):
        if self.make_error:
            raise self.make_error
        return self.target


__all__ = ["FakeClipboard", "FakeKeyboard", "FakeTarget", "FakeEnv", "focus", "TargetError"]
