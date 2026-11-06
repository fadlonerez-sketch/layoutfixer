"""Any Mac control that exposes its text through the Accessibility API - the Mac counterpart of UiaTarget.

Reading uses AXValue and AXSelectedTextRange, so the clipboard is not needed to
find out what to convert. Writing first selects exactly the characters to
change (AXSelectedTextRange) and waits until the app reports that selection -
Chromium applies it asynchronously, like UI Automation Select() on Windows.
Then:

* Cocoa controls (TextEdit, Notes, Mail, Safari's text fields...) get the new
  characters through AXSelectedText: no clipboard, and the app records an undo step.
* Chromium/Electron (Chrome, Edge, Brave, Slack, VS Code...) and Firefox, or any
  app that ignores AXSelectedText, get them pasted with ⌘V, the clipboard backed
  up and restored around it.

The field is read back after every write, and the original selection / caret is
put back. Never ⌘A.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from ..targets.base import FieldState, ReplaceResult, TargetError, TextTarget, Unsupported
from ..textindex import from_units, to_units
from ..textindex import normalize_newlines as norm

log = logging.getLogger(__name__)

TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
SECURE_ROLE = "AXSecureTextField"
PASTE_ONLY_MARKERS = ("ChromeAXNodeId",)            # attribute present on Chromium / Electron elements
PASTE_ONLY_BUNDLES = ("org.mozilla.",)              # Firefox applies AX writes in its content process


class PasterLike(Protocol):
    def paste(self, text: str, verify): ...


class AXTarget(TextTarget):
    kind = "ax"

    def __init__(self, ax, element, paster: PasterLike, bundle_id: str = "", max_read_chars: int = 1_000_000,
                 select_timeout_s: float = 1.0, sleep: Callable[[float], None] = time.sleep):
        self.ax = ax
        self.el = element
        self.paster = paster
        self.bundle_id = bundle_id
        self.max_read = max_read_chars
        self.select_timeout_s = select_timeout_s
        self.sleep = sleep
        self.role: str | None = None

    # ------------------------------------------------------------------ reading
    def _value(self) -> str:
        v = self.ax.get(self.el, "AXValue")
        return str(v) if isinstance(v, str) else ""

    def check_editable(self) -> None:
        role = self.ax.get(self.el, "AXRole")
        subrole = self.ax.get(self.el, "AXSubrole")
        self.role = str(role) if role is not None else None
        if role == SECURE_ROLE or subrole == SECURE_ROLE:
            raise TargetError("Password fields are not changed")
        if role not in TEXT_ROLES:
            raise Unsupported("The focused control is not a text field")
        if self.ax.get(self.el, "AXEnabled") is False:
            raise TargetError("This text field is disabled")
        if not isinstance(self.ax.get(self.el, "AXValue"), str):
            raise Unsupported("The focused control does not expose its text")
        if not self.ax.settable(self.el, "AXSelectedTextRange") and not self.ax.settable(self.el, "AXValue"):
            raise TargetError("This text field is read-only")

    def read(self) -> FieldState:
        self.check_editable()
        text = self._value()
        if len(text) >= self.max_read:
            raise TargetError("This field holds too much text; select the part to convert")
        rng = self.ax.get_range(self.el)
        if rng is None:
            return FieldState(text, len(text), len(text))
        loc, length = rng
        start = from_units(text, loc)
        end = from_units(text, loc + length)
        sel_text = self.ax.get(self.el, "AXSelectedText")
        if length and isinstance(sel_text, str) and sel_text and text[start:end] != sel_text:
            if text.count(sel_text) == 1:
                start = text.index(sel_text)
                return FieldState(text, start, start + len(sel_text))
            return FieldState(str(sel_text), 0, len(sel_text), selection_only=True)
        return FieldState(text, start, end)

    # ------------------------------------------------------------------ writing
    def _paste_only(self) -> bool:
        if self.bundle_id.startswith(PASTE_ONLY_BUNDLES):
            return True
        names = self.ax.names(self.el)
        return any(m in names for m in PASTE_ONLY_MARKERS)

    def _selection_is(self, location: int, length: int, expected: str) -> bool:
        if self.ax.get_range(self.el) != (location, length):
            return False
        sel = self.ax.get(self.el, "AXSelectedText")
        return not isinstance(sel, str) or norm(str(sel)) == norm(expected)

    def _wait_for_selection(self, location: int, length: int, expected: str) -> float | None:
        start = time.monotonic()
        while True:
            if self._selection_is(location, length, expected):
                return time.monotonic() - start
            if time.monotonic() - start >= self.select_timeout_s:
                return None
            self.sleep(0.005)

    def _select(self, text: str, a: int, b: int) -> None:
        ua, ub = to_units(text, a), to_units(text, b)
        if not self.ax.set_range(self.el, ua, ub - ua):
            raise TargetError("The application did not let Layout Fixer select the text; nothing was changed")
        waited = self._wait_for_selection(ua, ub - ua, text[a:b])
        if waited is None:
            log.info("AX select: the app did not report the requested %d-char selection within %.1f s",
                     b - a, self.select_timeout_s)
            raise TargetError("The application did not select the text to replace; nothing was changed")
        log.info("AX select: %d-%d of %d chars confirmed after %.0f ms", a, b, len(text), waited * 1000)

    def _restore_selection(self, state: FieldState, text: str) -> None:
        ua, ub = to_units(text, state.sel_start), to_units(text, state.sel_end)
        if not self.ax.set_range(self.el, ua, ub - ua):
            log.info("AX: could not put the selection back")

    def replace(self, state: FieldState, start: int, end: int, new_text: str) -> ReplaceResult:
        if state.selection_only:
            sel = self.ax.get(self.el, "AXSelectedText")
            if not isinstance(sel, str) or norm(str(sel)) != norm(state.text):
                raise TargetError("The selection changed; nothing was replaced")
            before = self._value()
            res = self.paster.paste(new_text, verify=lambda: norm(new_text) in norm(self._value())
                                    and self._value() != before)
            return _result(res)

        if self._value() != state.text:
            raise TargetError("The text changed while converting; nothing was replaced")
        a, b = start, end  # only the characters that change: the rest keeps its formatting
        self._select(state.text, a, b)
        piece = new_text[a:b]

        if not self._paste_only() and self.ax.settable(self.el, "AXSelectedText"):
            if self.ax.set(self.el, "AXSelectedText", piece):
                after = self._value()
                if after == new_text:
                    log.info("AX write: AXSelectedText, read back and verified")
                    self._restore_selection(state, new_text)
                    return ReplaceResult(True)
                if after != state.text:
                    raise TargetError("The text was changed but does not read back as expected - press ⌘Z if "
                                      "it looks wrong", changed=True)
                log.info("AX write: the app ignored AXSelectedText; pasting instead")
                if not self._selection_is(to_units(state.text, a), to_units(state.text, b) - to_units(state.text, a),
                                          state.text[a:b]):
                    self._select(state.text, a, b)

        expected = norm(new_text)
        res = self.paster.paste(piece, verify=lambda: norm(self._value()) == expected)
        if not res.verified and not res.clipboard_note and norm(self._value()) == norm(state.text):
            raise TargetError("The application did not accept the paste; nothing was changed")
        if res.verified:
            self._restore_selection(state, new_text)
        return _result(res)


def _result(res) -> ReplaceResult:
    notes = [n for n in (res.clipboard_note, "" if res.verified else "could not verify the result") if n]
    return ReplaceResult(res.verified, "; ".join(notes))
