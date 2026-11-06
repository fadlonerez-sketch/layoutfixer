"""Paste text into the focused control through the clipboard, then restore the clipboard."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .clipboard import ClipboardBackend, ClipboardGuard
from .targets.base import TargetError

log = logging.getLogger(__name__)

NOT_RESPONDING = "the app is not responding - the converted text was left on the clipboard"
NOT_RESTORED = "your clipboard could not be restored"


class KeyboardLike(Protocol):
    def wait_for_release(self) -> bool: ...
    def copy(self) -> bool: ...
    def paste(self) -> bool: ...


@dataclass(frozen=True)
class PasteResult:
    verified: bool
    clipboard_note: str = ""  # set when the user's clipboard was not put back


def clipboard_note(guard: ClipboardGuard) -> str:
    if guard.abandoned:
        return NOT_RESPONDING
    return NOT_RESTORED if guard.failed else ""


class ClipboardPaster:
    def __init__(self, backend: ClipboardBackend, keyboard: KeyboardLike, verify_timeout_s: float = 1.5,
                 blind_delay_s: float = 0.6, poll_s: float = 0.03, sleep: Callable[[float], None] = time.sleep,
                 wait_idle: Callable[[], bool] = lambda: True):
        self.backend = backend
        self.keyboard = keyboard
        self.verify_timeout_s = verify_timeout_s
        self.blind_delay_s = blind_delay_s
        self.poll_s = poll_s
        self.sleep = sleep
        self.wait_idle = wait_idle  # True once the target app processes messages again

    def _watch(self, verify: Callable[[], bool]) -> bool:
        deadline = time.monotonic() + self.verify_timeout_s
        while True:
            try:
                if verify():
                    return True
            except Exception as e:  # the control may be busy re-rendering
                log.debug("verify failed: %s", e)
            if time.monotonic() >= deadline:
                return False
            self.sleep(self.poll_s)

    def paste(self, text: str, verify: Callable[[], bool] | None) -> PasteResult:
        """Ctrl+V ``text``; ``verify()`` confirms the result.

        The clipboard is restored only once the paste was seen in the field. If it isn't seen in
        time, we wait until the app responds again and give it a second window; an app that stays
        unresponsive keeps our text on the clipboard, because restoring then could make its late
        paste insert the user's old clipboard into the field.
        """
        guard = ClipboardGuard(self.backend).__enter__()
        try:
            guard.set_text(text)
            if not self.keyboard.paste():
                raise TargetError("Windows did not accept the paste keystroke; nothing was changed")
            if verify is None:
                self.sleep(self.blind_delay_s)
                verified = False
                if not self.wait_idle():
                    guard.abandon("target not responding")
            else:
                verified = self._watch(verify)
                if not verified:
                    log.info("paste not confirmed within %.1fs; waiting for the app", self.verify_timeout_s)
                    if self.wait_idle():
                        verified = self._watch(verify)
                    else:
                        guard.abandon("target not responding")
        finally:
            guard.restore()
        return PasteResult(verified, clipboard_note(guard))
