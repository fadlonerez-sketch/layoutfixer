"""One conversion, start to finish, plus the dispatcher that keeps hotkey presses from overlapping.

The engine talks to Windows only through an ``Environment`` object, so the
whole flow runs in tests against fakes (see tests/fakes.py); WindowsEnvironment
in win_env.py is the real one.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

from .config import Settings
from .converter import Direction, convert, direction_for_layout
from .env_types import SwitchResult
from .targets.base import FieldState, TargetError, TextTarget

if TYPE_CHECKING:
    from .win.focus import FocusInfo  # macOS passes mac.env.MacFocus (same attributes used here)

log = logging.getLogger(__name__)

ADMIN_MESSAGE = ("This window belongs to a program running as administrator. Windows does not let "
                 "Layout Fixer change it unless Layout Fixer also runs as administrator")
UNDO_KEYS = "⌘Z" if sys.platform == "darwin" else "Ctrl+Z"


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str
    level: str = "error"  # success | warning | error | silent
    direction: Direction | None = None
    strategy: str = ""


class Environment(Protocol):
    keyboard: object

    def focus(self) -> FocusInfo | None: ...
    def is_blocked(self, focus: FocusInfo) -> bool: ...
    def current_lang(self, focus: FocusInfo) -> str | None: ...
    def switch_layout(self, focus: FocusInfo, lang: str) -> SwitchResult: ...
    def make_target(self, focus: FocusInfo, settings: Settings) -> TextTarget: ...


def _fail(message: str, level: str = "error", strategy: str = "", stage: str = "") -> Outcome:
    if stage:
        log.info("FAILED at %s: %s", stage, message)  # messages never contain field text
    return Outcome(False, message, level, None, strategy)


OBJECT_CHAR = "￼"  # stands for an embedded image/object (emoji pictures in chat apps, OLE objects)


def changed_segments(old: str, new: str) -> list[tuple[int, int]]:
    """Ranges to replace: the differing characters, split around embedded objects.

    Replacing a range that contains U+FFFC would turn the real object into a plain
    placeholder character, so objects are never inside a replaced range.
    """
    segments: list[tuple[int, int]] = []
    start = last = None
    for i, (o, n) in enumerate(zip(old, new)):
        if o == OBJECT_CHAR:
            if start is not None:
                segments.append((start, last + 1))  # type: ignore[operator]
                start = None
            continue
        if o != n:
            if start is None:
                start = i
            last = i
    if start is not None:
        segments.append((start, last + 1))  # type: ignore[operator]
    return segments


class Engine:
    def __init__(self, env: Environment, settings: Callable[[], Settings], own_pid: int | None = None):
        self.env = env
        self.settings = settings
        self.own_pid = os.getpid() if own_pid is None else own_pid

    def run(self, force: Direction | None = None) -> Outcome:
        """One press of the shortcut. Every step logs what it found (never the text itself)."""
        settings = self.settings()
        focus = self.env.focus()
        if focus is None:
            return _fail("No window has the keyboard focus", stage="focus")
        log.info("focus: process=%s pid=%d class=%s caret=%s", focus.process_name or "?", focus.pid,
                 focus.class_name, focus.has_caret)
        if focus.pid == self.own_pid:
            return _fail("", "silent", stage="focus (Layout Fixer's own window)")
        if self.env.is_blocked(focus):
            return _fail(ADMIN_MESSAGE, stage="focus")
        lang = self.env.current_lang(focus)
        direction = force or direction_for_layout(lang)
        log.info("layout: active=%s -> direction=%s%s", lang, direction and direction.value,
                 " (forced)" if force else "")
        if direction is None:
            return _fail("The active keyboard layout is neither English nor Hebrew - nothing was changed",
                         stage="layout")
        if not self.env.keyboard.wait_for_release():
            return _fail("Release the shortcut keys and try again - nothing was changed", stage="keys")
        try:
            target = self.env.make_target(focus, settings)
        except TargetError as e:
            return _fail(str(e), stage="find text field")
        log.info("target: %s", target.kind)
        try:
            return self._convert(focus, target, settings, direction)
        except TargetError as e:
            return _fail(str(e), "warning" if e.changed else "error", target.kind, stage=f"{target.kind} target")
        except Exception:
            log.exception("conversion failed")
            return _fail(f"Unexpected error (see the log). If the text looks wrong, press {UNDO_KEYS}",
                         strategy=target.kind)
        finally:
            try:
                target.close()
            except Exception:
                log.exception("cleanup failed")

    def _convert(self, focus: FocusInfo, target: TextTarget, settings: Settings,
                 direction: Direction) -> Outcome:
        state = target.read()
        log.info("read: %d chars, selection %d-%d, selection_only=%s", len(state.text), state.sel_start,
                 state.sel_end, state.selection_only)
        if state.has_selection:
            s0, e0 = state.sel_start, state.sel_end
        else:
            s0, e0 = 0, len(state.text)
            if e0 > settings.max_whole_field_chars:
                return _fail(f"This field has {e0:,} characters - select the part to convert "
                             f"(limit {settings.max_whole_field_chars:,} without a selection)",
                             strategy=target.kind, stage="read")
        scope = state.text[s0:e0]
        if not scope.strip():
            return _fail("The text field is empty" if not state.has_selection else "Nothing to convert",
                         strategy=target.kind, stage="read")
        tables = getattr(self.env, "key_tables", None)  # macOS: the Mac layouts' own keys
        conversion = convert(scope, direction, tables(direction) if tables else None)
        if not conversion.changed:
            return _fail("Nothing to convert (no characters of the " +
                         ("English" if direction is Direction.EN_TO_HE else "Hebrew") + " layout)",
                         strategy=target.kind, stage="convert")
        new_text = state.text[:s0] + conversion.text + state.text[e0:]
        segments = changed_segments(state.text, new_text)
        if state.selection_only:
            if OBJECT_CHAR in state.text:
                return _fail("The selection contains a picture or object - select only the text to convert",
                             strategy=target.kind, stage="convert")
            segments = [(0, len(state.text))]  # this target can only replace the selection as a whole
        log.info("convert: %s, %d chars in scope, %d segment(s) to replace", direction.value, len(scope),
                 len(segments))
        verified = True
        note = ""
        current = state
        for a, b in reversed(segments):
            step = current.text[:a] + new_text[a:b] + current.text[b:]
            try:
                result = target.replace(current, a, b, step)
            except TargetError as e:
                if current is not state:  # earlier segments are already converted
                    raise TargetError(f"{e} (part of the text was converted - {UNDO_KEYS} undoes it)", changed=True)
                raise
            verified = verified and result.verified
            note = note or result.note
            current = FieldState(step, state.sel_start, state.sel_end, state.selection_only)
        log.info("replace: done, read back and verified=%s%s", verified, f" ({note})" if note else "")

        notes = []
        if not verified:
            notes.append(note or "could not verify")
        if settings.switch_layout:
            switch = self.env.switch_layout(focus, direction.target_lang)
            log.info("switch layout: ok=%s before=%s after=%s (%s)", switch.ok, switch.before, switch.after,
                     switch.message)
            if not switch.ok:
                notes.append(f"the keyboard was NOT switched to {direction.label}: {switch.message}")
        message = f"Converted to {direction.label}"
        if notes:
            message += " - " + "; ".join(notes)
        return Outcome(True, message, "warning" if notes else "success", direction, target.kind)


_STOP = object()


class Dispatcher:
    """Runs conversions one at a time on a worker thread.

    A press while a conversion is running, or within ``cooldown_s`` after one
    finished, is dropped - so a bouncing key or a double press cannot convert
    the text there and straight back. Presses after the cooldown are handled
    normally (pressing again converts back, which works as an undo).
    """

    def __init__(self, run: Callable[[Direction | None], Outcome], on_outcome: Callable[[Outcome], None],
                 cooldown_s: Callable[[], float] | float = 0.4):
        self._run = run
        self._on_outcome = on_outcome
        self._cooldown = cooldown_s if callable(cooldown_s) else (lambda: cooldown_s)
        self._lock = threading.Lock()
        self._busy = False
        self._last_end = -1e9
        self._jobs: queue.Queue = queue.Queue()
        self.dropped = 0
        self._thread = threading.Thread(target=self._worker, name="LayoutFixer-worker", daemon=True)
        self._thread.start()

    def trigger(self, force: Direction | None = None) -> bool:
        with self._lock:
            if self._busy or time.monotonic() - self._last_end < self._cooldown():
                self.dropped += 1
                log.info("hotkey ignored (busy or within cooldown)")
                return False
            self._busy = True
        self._jobs.put(force)
        return True

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            if job is _STOP:
                return
            try:
                outcome = self._run(job)
            except Exception:
                log.exception("engine crashed")
                outcome = _fail("Unexpected error (see the log)")
            finally:
                with self._lock:
                    self._busy = False
                    self._last_end = time.monotonic()
            try:
                self._on_outcome(outcome)
            except Exception:
                log.exception("outcome handler failed")

    def stop(self, timeout: float = 3.0) -> None:
        self._jobs.put(_STOP)
        self._thread.join(timeout)
