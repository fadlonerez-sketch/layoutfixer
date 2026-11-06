"""Win32Clipboard logic against an in-memory FAKE of the user32/kernel32 calls.

Nothing here touches the real clipboard: Win32Clipboard.api is replaced by FakeWinApi, which keeps
the "clipboard" in a dict and hands out ctypes buffers as global memory handles. Covers the
security-relevant parts that otherwise only the opt-in real-clipboard test reaches: the temporary
text is excluded from clipboard history / monitors, the restore keeps newer content, and nothing
logs the text.
"""

import ctypes
import logging

import pytest

from layoutfixer import clipboard as cm
from layoutfixer.clipboard import ClipboardGuard, Win32Clipboard
from layoutfixer.win import api as real_api


def _text(s: str) -> bytes:
    return (s + "\0").encode("utf-16-le")


class FakeWinApi:
    """The subset of layoutfixer.win.api that Win32Clipboard uses, backed by a dict."""

    def __init__(self, initial: dict[int, bytes] | None = None):
        for name in dir(real_api):
            if name.startswith(("CF_", "GMEM_", "HWND_")):
                setattr(self, name, getattr(real_api, name))
        self.data: dict[int, int] = {}  # format -> handle (insertion order = enumeration order)
        self.mem: dict[int, ctypes.Array] = {}
        self.names: dict[int, str] = {}
        self.seq = 1
        self.open_owner = None
        self.busy = 0  # number of OpenClipboard calls that fail (someone else holds it)
        self.windows = set()
        self._next = 1000
        for fmt, payload in (initial or {}).items():
            self.data[fmt] = self.GlobalAlloc(0, len(payload))
            ctypes.memmove(self.GlobalLock(self.data[fmt]), payload, len(payload))

    # windows
    def CreateWindowExW(self, *args):  # noqa: N802
        self._next += 1
        self.windows.add(self._next)
        return self._next

    def DestroyWindow(self, hwnd):  # noqa: N802
        self.windows.discard(hwnd)
        return True

    # clipboard
    def OpenClipboard(self, owner):  # noqa: N802
        if self.busy:
            self.busy -= 1
            return False
        assert self.open_owner is None, "clipboard opened twice"
        self.open_owner = owner
        return True

    def CloseClipboard(self):  # noqa: N802
        assert self.open_owner is not None
        self.open_owner = None
        return True

    def EmptyClipboard(self):  # noqa: N802
        assert self.open_owner is not None
        self.data.clear()
        self.seq += 1
        return True

    def SetClipboardData(self, fmt, h):  # noqa: N802
        assert self.open_owner is not None
        self.data[fmt] = h
        self.seq += 1
        return h

    def GetClipboardData(self, fmt):  # noqa: N802
        assert self.open_owner is not None
        return self.data.get(fmt, 0)

    def EnumClipboardFormats(self, fmt):  # noqa: N802
        order = list(self.data)
        if fmt == 0:
            return order[0] if order else 0
        i = order.index(fmt) + 1
        return order[i] if i < len(order) else 0

    def GetClipboardSequenceNumber(self):  # noqa: N802
        return self.seq

    def RegisterClipboardFormatW(self, name):  # noqa: N802
        for fmt, known in self.names.items():
            if known == name:
                return fmt
        fmt = 0xC000 + len(self.names) + 1
        self.names[fmt] = name
        return fmt

    def GetClipboardFormatNameW(self, fmt, buf, size):  # noqa: N802
        name = self.names.get(fmt, "")
        buf.value = name[: size - 1]
        return len(name)

    # global memory
    def GlobalAlloc(self, flags, size):  # noqa: N802
        self._next += 1
        self.mem[self._next] = ctypes.create_string_buffer(size)
        return self._next

    def GlobalLock(self, h):  # noqa: N802
        return ctypes.addressof(self.mem[h]) if h in self.mem else 0

    def GlobalUnlock(self, h):  # noqa: N802
        return True

    def GlobalFree(self, h):  # noqa: N802
        self.mem.pop(h, None)
        return 0

    def GlobalSize(self, h):  # noqa: N802
        return ctypes.sizeof(self.mem[h])

    # helpers for assertions
    def payload(self, fmt: int) -> bytes:
        return bytes(self.mem[self.data[fmt]])

    def formats_named(self) -> dict[str, bytes]:
        return {self.names[f]: self.payload(f) for f in self.data if f in self.names}


ORIGINAL = {real_api.CF_UNICODETEXT: _text("precious user data"), 0xC0FF: b"<b>html</b>"}
SECRET = "סוד secret 12345"
FLAG = (0).to_bytes(4, "little")


def make(initial=None) -> tuple[Win32Clipboard, FakeWinApi]:
    cb = Win32Clipboard(open_retries=3, retry_delay_s=0)
    fake = FakeWinApi(ORIGINAL if initial is None else initial)
    fake.names[0xC0FF] = "HTML Format"
    cb.api = fake
    return cb, fake


def test_temporary_text_is_hidden_from_history_and_clipboard_monitors():
    cb, fake = make()
    assert cb.set_text(SECRET)
    assert fake.payload(real_api.CF_UNICODETEXT) == _text(SECRET)
    flags = fake.formats_named()
    for name in cm.EXCLUDE_FORMATS + cm.NO_HISTORY_FORMATS:
        assert flags.get(name) == FLAG, name
    assert fake.open_owner is None and not fake.windows  # closed, owner window destroyed


def test_guard_round_trip_restores_every_format_and_skips_history():
    cb, fake = make()
    with ClipboardGuard(cb) as g:
        g.set_text(SECRET)
        assert cb.get_text() == SECRET
    assert not g.failed
    assert fake.payload(real_api.CF_UNICODETEXT) == ORIGINAL[real_api.CF_UNICODETEXT]
    assert fake.payload(0xC0FF) == ORIGINAL[0xC0FF]
    flags = fake.formats_named()
    for name in cm.NO_HISTORY_FORMATS:  # the user's own copy is already in history once
        assert flags.get(name) == FLAG, name
    for name in cm.EXCLUDE_FORMATS:  # the restored content is the user's: monitors may see it again
        assert name not in flags
    assert SECRET.encode("utf-16-le") not in b"".join(fake.payload(f) for f in fake.data)


def test_restore_keeps_newer_content_copied_meanwhile():
    cb, fake = make()
    with ClipboardGuard(cb) as g:
        g.set_text(SECRET)
        fake.open_owner = "user"
        fake.EmptyClipboard()
        fake.SetClipboardData(real_api.CF_UNICODETEXT, fake.GlobalAlloc(0, 8))
        ctypes.memmove(fake.GlobalLock(fake.data[real_api.CF_UNICODETEXT]), _text("new"), 8)
        fake.open_owner = None
    assert cb.get_text() == "new" and not g.failed


def test_empty_clipboard_backup_is_restored_as_empty():
    cb, fake = make(initial={})
    with ClipboardGuard(cb) as g:
        g.set_text(SECRET)
    assert fake.data == {} and not g.failed


def test_snapshot_skips_gdi_and_private_handles_and_names_registered_formats():
    cb, fake = make()
    fake.data[real_api.CF_BITMAP] = 1234  # a GDI handle, not global memory
    fake.data[real_api.CF_PRIVATEFIRST + 1] = 1235
    snap = cb.snapshot()
    assert [f for f, _k, _p in snap.items] == [real_api.CF_UNICODETEXT, 0xC0FF]
    assert set(snap.skipped) == {real_api.CF_BITMAP, real_api.CF_PRIVATEFIRST + 1}
    assert snap.names == {0xC0FF: "HTML Format"}


def test_busy_clipboard_raises_and_releases_owner_window():
    cb, fake = make()
    fake.busy = 10
    with pytest.raises(cm.ClipboardError):
        cb.set_text(SECRET)
    assert not fake.windows and fake.payload(real_api.CF_UNICODETEXT) == ORIGINAL[real_api.CF_UNICODETEXT]


def test_clipboard_code_never_logs_the_text(caplog):
    caplog.set_level(logging.DEBUG)
    cb, fake = make()
    fake.data[real_api.CF_BITMAP] = 1234  # forces the "not copyable" info lines
    with ClipboardGuard(cb) as g:
        g.set_text(SECRET)
    g2 = ClipboardGuard(cb).__enter__()
    g2.set_text(SECRET)
    g2.abandon("target not responding")
    g3 = ClipboardGuard(cb).__enter__()
    g3.set_text(SECRET)
    fake.busy = 1000
    g3.restore_timeout_s = 0
    g3.restore()  # fails and logs
    assert g3.failed
    assert caplog.records  # the paths above did log
    for needle in (SECRET, "secret", "סוד", "precious", "html"):
        assert needle not in caplog.text
