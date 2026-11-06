"""Clipboard backup/restore logic (SIMULATED clipboard), plus opt-in real-clipboard tests.

The real-clipboard tests modify and restore the system clipboard, so they only run with
LAYOUTFIXER_REAL_CLIPBOARD_TESTS=1.
"""

import os

import pytest

from fakes import FakeClipboard, FakeKeyboard
from layoutfixer.clipboard import ClipboardError, ClipboardGuard
from layoutfixer.paste import ClipboardPaster
from layoutfixer.targets.base import TargetError

ORIGINAL = {13: "precious\0".encode("utf-16-le"), 0xC123: b"\x00html"}


def test_guard_restores_after_use():
    clip = FakeClipboard(ORIGINAL)
    with ClipboardGuard(clip) as g:
        g.set_text("temp")
        assert clip.get_text() == "temp"
    assert clip.formats == ORIGINAL


def test_guard_restores_after_exception():
    clip = FakeClipboard(ORIGINAL)
    with pytest.raises(RuntimeError):
        with ClipboardGuard(clip) as g:
            g.set_text("temp")
            raise RuntimeError("fail")
    assert clip.formats == ORIGINAL


def test_guard_untouched_clipboard_is_not_rewritten():
    clip = FakeClipboard(ORIGINAL)
    with ClipboardGuard(clip):
        pass
    assert clip.restores == 0 and clip.formats == ORIGINAL


def test_guard_keeps_newer_content_from_someone_else():
    clip = FakeClipboard(ORIGINAL)
    with ClipboardGuard(clip) as g:
        g.set_text("temp")
        clip.external_copy("user copied this")
    assert clip.get_text() == "user copied this"


def test_guard_set_failure_raises():
    clip = FakeClipboard(ORIGINAL)
    clip.fail_set = True
    with pytest.raises(ClipboardError):
        with ClipboardGuard(clip) as g:
            g.set_text("temp")
    assert clip.formats == ORIGINAL


def test_empty_clipboard_restored_as_empty():
    clip = FakeClipboard()
    with ClipboardGuard(clip) as g:
        g.set_text("temp")
    assert clip.formats == {}


def test_paster_waits_for_verification_before_restoring():
    clip = FakeClipboard(ORIGINAL)
    keys = FakeKeyboard()
    field = {"text": "akuo"}
    seen_during_paste = []
    keys.on_paste = lambda: seen_during_paste.append(clip.get_text())
    polls = []

    def verify():
        polls.append(clip.get_text())  # clipboard must still hold our text while we wait
        if len(polls) == 3:
            field["text"] = "שלום"
        return field["text"] == "שלום"

    p = ClipboardPaster(clip, keys, verify_timeout_s=2, poll_s=0.001)
    assert p.paste("שלום", verify).verified is True
    assert seen_during_paste == ["שלום"] and polls == ["שלום"] * 3
    assert clip.formats == ORIGINAL


def test_paster_timeout_restores_and_reports():
    clip = FakeClipboard(ORIGINAL)
    p = ClipboardPaster(clip, FakeKeyboard(), verify_timeout_s=0.05, poll_s=0.01)
    assert p.paste("x", lambda: False).verified is False
    assert clip.formats == ORIGINAL


def test_paster_keystroke_rejected():
    clip = FakeClipboard(ORIGINAL)
    keys = FakeKeyboard()
    keys.accept = False
    p = ClipboardPaster(clip, keys)
    with pytest.raises(TargetError):
        p.paste("x", lambda: True)
    assert clip.formats == ORIGINAL


def test_late_paste_after_app_becomes_responsive_is_confirmed():
    """The app is slow: the paste shows up only after the first window; the clipboard waits for it."""
    clip = FakeClipboard(ORIGINAL)
    state = {"polls": 0, "idle_called": False}

    def verify():
        state["polls"] += 1
        assert clip.get_text() == "x"  # still our text while the app catches up
        return state["idle_called"] and state["polls"] > 5

    def idle():
        state["idle_called"] = True
        return True

    p = ClipboardPaster(clip, FakeKeyboard(), verify_timeout_s=0.05, poll_s=0.01, wait_idle=idle)
    res = p.paste("x", verify)
    assert res.verified and res.clipboard_note == ""
    assert clip.formats == ORIGINAL


def test_hung_app_keeps_converted_text_on_clipboard():
    """Restoring while the app is hung could make its late paste insert the old clipboard."""
    clip = FakeClipboard(ORIGINAL)
    p = ClipboardPaster(clip, FakeKeyboard(), verify_timeout_s=0.02, poll_s=0.01, wait_idle=lambda: False)
    res = p.paste("x", lambda: False)
    assert not res.verified and "not responding" in res.clipboard_note
    assert clip.get_text() == "x"


def test_restore_retries_while_clipboard_is_held_open():
    clip = FakeClipboard(ORIGINAL)
    clip.busy_restores = 3
    with ClipboardGuard(clip) as g:
        g.set_text("temp")
    assert not g.failed and clip.formats == ORIGINAL


def test_restore_gives_up_without_raising_and_reports():
    clip = FakeClipboard(ORIGINAL)
    clip.busy_restores = 10_000
    p = ClipboardPaster(clip, FakeKeyboard(), verify_timeout_s=0.02, poll_s=0.01)
    import layoutfixer.clipboard as cm
    orig = cm.ClipboardGuard.__init__

    def short(self, backend):
        orig(self, backend)
        self.restore_timeout_s = 0.2

    cm.ClipboardGuard.__init__ = short
    try:
        res = p.paste("x", lambda: True)
    finally:
        cm.ClipboardGuard.__init__ = orig
    assert res.verified and "could not be restored" in res.clipboard_note


def test_failed_set_text_still_restores_backup():
    clip = FakeClipboard(ORIGINAL)
    clip.fail_set = True  # emptied the clipboard, then failed
    with pytest.raises(ClipboardError):
        with ClipboardGuard(clip) as g:
            g.set_text("temp")
    assert clip.formats == ORIGINAL


def test_restore_checks_sequence_while_holding_the_clipboard():
    clip = FakeClipboard(ORIGINAL)
    g = ClipboardGuard(clip).__enter__()
    g.set_text("temp")
    clip.external_copy("user")  # lands just before the restore opens the clipboard
    g.restore()
    assert clip.get_text() == "user" and not g.failed


REAL = os.environ.get("LAYOUTFIXER_REAL_CLIPBOARD_TESTS") == "1"


@pytest.mark.clipboard
@pytest.mark.skipif(not REAL, reason="opt-in: modifies and restores the real clipboard")
def test_real_clipboard_round_trip():
    from layoutfixer.clipboard import Win32Clipboard
    cb = Win32Clipboard()
    with ClipboardGuard(cb) as g:
        before = cb.get_text()
        g.set_text("Layout Fixer test שלום")
        assert cb.get_text() == "Layout Fixer test שלום"
    assert cb.get_text() == before
