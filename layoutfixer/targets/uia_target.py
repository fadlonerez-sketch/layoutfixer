"""Any control that exposes its text through UI Automation (browsers, Electron, WPF, Qt, UWP, Office...).

Reading uses the Text pattern (or the Value pattern), so the clipboard is not
needed to find out what to convert. Writing selects exactly the characters to
change through UI Automation, waits until the control reports that very text as
selected (Chromium applies Select() asynchronously, a few milliseconds later),
and only then pastes; the result is read back to verify it. If the
exact range cannot be selected the whole field is selected the same way - never
with Ctrl+A, which in many apps selects the entire page or document.
Controls with only a Value pattern are written with ValuePattern.SetValue.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from ..textindex import normalize_newlines as norm
from ..textindex import to_units
from ..uia import (Endpoint_End, Endpoint_Start, TextUnit_Character, UIA_DocumentControlTypeId,
                   UIA_EditControlTypeId, UIA_IsReadOnlyAttributeId)
from .base import FieldState, ReplaceResult, TargetError, TextTarget, Unsupported

log = logging.getLogger(__name__)


class PasterLike(Protocol):
    def paste(self, text: str, verify) -> bool: ...


class UiaTarget(TextTarget):
    kind = "uia"

    def __init__(self, client, element, paster: PasterLike, max_read_chars: int = 1_000_000,
                 select_timeout_s: float = 1.0):
        self.client = client
        self.select_timeout_s = select_timeout_s
        self.el = element
        self.paster = paster
        self.max_read = max_read_chars
        self.control_type = None
        self.tp = client.text_pattern(element)
        self.vp = client.value_pattern(element)

    # ------------------------------------------------------------------ reading
    def _doc_text(self) -> str:
        if self.tp is not None:
            return self.tp.DocumentRange.GetText(self.max_read)
        return self.vp.CurrentValue or ""

    def _selection(self):
        sels = self.tp.GetSelection()
        if not sels or sels.Length != 1:
            return None
        return sels.GetElement(0)

    def check_editable(self) -> None:
        el = self.el
        try:
            if el.CurrentIsPassword:
                raise TargetError("Password fields are not changed")
            enabled = el.CurrentIsEnabled
            control_type = el.CurrentControlType
            self.control_type = control_type
        except TargetError:
            raise
        except Exception as e:
            raise Unsupported(f"The focused control could not be inspected ({e.__class__.__name__})")
        if not enabled:
            raise TargetError("This text field is disabled")
        if self.tp is None and self.vp is None:
            raise Unsupported("The focused control does not expose its text")
        # Windows, panes, sliders... can carry a writable Value pattern too; only text controls qualify.
        if control_type not in (UIA_EditControlTypeId, UIA_DocumentControlTypeId):
            raise Unsupported("The focused control is not a text field")
        if self.vp is not None and self.vp.CurrentIsReadOnly:
            raise TargetError("This text field is read-only")
        if self.tp is not None:
            ro = self.tp.DocumentRange.GetAttributeValue(UIA_IsReadOnlyAttributeId)
            if ro is True:
                raise TargetError("The focused text is read-only (not an input field)")

    def read(self) -> FieldState:
        self.check_editable()
        text = self._doc_text()
        if len(text) >= self.max_read:
            raise TargetError("This field holds too much text; select the part to convert")
        if self.tp is None:
            return FieldState(text, len(text), len(text))  # Value pattern: no selection information
        sel = self._selection()
        if sel is None:
            return FieldState(text, len(text), len(text))
        sel_text = sel.GetText(self.max_read)
        pre = self.tp.DocumentRange.Clone()
        pre.MoveEndpointByRange(Endpoint_End, sel, Endpoint_Start)
        start = len(pre.GetText(self.max_read))
        end = start + len(sel_text)
        if text[start:end] == sel_text:
            return FieldState(text, start, end)
        if sel_text and text.count(sel_text) == 1:
            start = text.index(sel_text)
            return FieldState(text, start, start + len(sel_text))
        if sel_text:
            # Offsets don't line up (line-break handling differs); work on the selection alone.
            return FieldState(sel_text, 0, len(sel_text), selection_only=True)
        caret = min(start, len(text))
        return FieldState(text, caret, caret)

    # ------------------------------------------------------------------ writing
    def _selection_is(self, expected: str) -> bool:
        sel = self._selection()
        return sel is not None and norm(sel.GetText(self.max_read)) == norm(expected)

    def _wait_for_selection(self, expected: str) -> float | None:
        """Seconds until the control reports ``expected`` as its selection, None if it never does.

        Select() only requests the selection. Chromium (Chrome, Edge, Electron) applies it in the
        renderer process and reports it a few milliseconds later, so the selection is polled
        rather than checked once."""
        start = time.monotonic()
        while True:
            if self._selection_is(expected):
                return time.monotonic() - start
            if time.monotonic() - start >= self.select_timeout_s:
                return None
            time.sleep(0.005)

    def _range_for(self, text: str, a: int, b: int):
        """A text range covering text[a:b], or None if the control counts characters differently."""
        want = norm(text[a:b])
        candidates = dict.fromkeys([(a, b), (to_units(text, a), to_units(text, b)),
                                    (to_units(text, a, True), to_units(text, b, True))])
        for ua, ub in candidates:
            r = self.tp.DocumentRange.Clone()
            r.MoveEndpointByRange(Endpoint_End, r, Endpoint_Start)
            if ub:
                r.MoveEndpointByUnit(Endpoint_End, TextUnit_Character, ub)
            if ua:
                r.MoveEndpointByUnit(Endpoint_Start, TextUnit_Character, ua)
            if norm(r.GetText(self.max_read)) == want:
                return r
        return None

    def replace(self, state: FieldState, start: int, end: int, new_text: str) -> ReplaceResult:
        if self.tp is None:
            return self._replace_value(state, new_text)
        if state.selection_only:
            if not self._selection_is(state.text):
                raise TargetError("The selection changed; nothing was replaced")
            before = self._doc_text()
            res = self.paster.paste(new_text, verify=lambda: norm(new_text) in norm(self._doc_text())
                                    and self._doc_text() != before)
            return _result(res)

        if self._doc_text() != state.text:
            raise TargetError("The text changed while converting; nothing was replaced")
        a, b = start, end  # only the characters that change: the rest keeps its formatting
        if (a, b) != (state.sel_start, state.sel_end) or not self._selection_is(state.text[a:b]):
            rng = self._range_for(state.text, a, b)
            if rng is None:
                # The control counts characters differently; fall back to the whole field, unless
                # that would paste over pictures/objects (U+FFFC) and destroy them.
                if "\ufffc" in state.text:
                    raise TargetError("Could not select the exact text safely; nothing was changed")
                if self.control_type != UIA_EditControlTypeId:
                    # A document (Word, rich web editors) would lose its formatting, links and tables.
                    raise TargetError("Could not select the exact text in this document - select the "
                                      "words to convert and try again; nothing was changed")
                a, b = 0, len(state.text)
                rng = self.tp.DocumentRange
            rng.Select()
            waited = self._wait_for_selection(state.text[a:b])
            if waited is None:
                sel = self._selection()
                log.info("UIA select: the control did not report the requested %d-char selection within %.1f s "
                         "(it reports %s chars)", b - a, self.select_timeout_s,
                         len(sel.GetText(self.max_read)) if sel is not None else "no selection, 0")
                raise TargetError("The application did not select the text to replace; nothing was changed")
            log.info("UIA select: %d-%d of %d chars confirmed after %.0f ms", a, b, len(state.text), waited * 1000)

        expected = norm(new_text)
        res = self.paster.paste(new_text[a:b], verify=lambda: norm(self._doc_text()) == expected)
        if not res.verified and not res.clipboard_note and norm(self._doc_text()) == norm(state.text):
            raise TargetError("The application did not accept the paste; nothing was changed")
        return _result(res)

    def _replace_value(self, state: FieldState, new_text: str) -> ReplaceResult:
        if (self.vp.CurrentValue or "") != state.text:
            raise TargetError("The text changed while converting; nothing was replaced")
        self.vp.SetValue(new_text)
        after = self.vp.CurrentValue or ""
        if norm(after) == norm(new_text):
            return ReplaceResult(True)
        if norm(after) == norm(state.text):
            raise TargetError("The field did not accept the new text; nothing was changed")
        return ReplaceResult(False, "could not verify the result")


def _result(res) -> ReplaceResult:
    notes = [n for n in (res.clipboard_note, "" if res.verified else "could not verify the result") if n]
    return ReplaceResult(res.verified, "; ".join(notes))
