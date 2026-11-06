"""Clipboard backup / temporary text / restore.

Only the paste-based replacement uses the clipboard. ClipboardGuard backs up
every format it can copy, puts the converted text on the clipboard (marked so
Windows clipboard history and clipboard managers skip it) and puts the backup
back afterwards - also when the operation failed. If something else changed
the clipboard in the meantime (the user copied something new), that newer
content is kept and the backup is dropped.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

EXCLUDE_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")
NO_HISTORY_FORMATS = ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")


@dataclass
class Snapshot:
    """Clipboard contents in their original order. ``items``: (format id, kind, payload)."""
    items: list[tuple[int, str, object]] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)  # formats that cannot be copied (GDI handles, private)
    names: dict[int, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.items and not self.skipped


class ClipboardBackend(Protocol):
    def sequence(self) -> int: ...
    def snapshot(self) -> Snapshot: ...
    def restore(self, snap: Snapshot, expected_seq: int | None = None) -> str: ...  # restored|changed|failed
    def set_text(self, text: str) -> bool: ...
    def get_text(self) -> str | None: ...
    def discard(self, snap: Snapshot) -> None: ...


class ClipboardError(RuntimeError):
    pass


class ClipboardGuard:
    """Use as a context manager; restores on exit unless already restored."""

    def __init__(self, backend: ClipboardBackend):
        self.backend = backend
        self.snap: Snapshot | None = None
        self._ours: int | None = None  # sequence number after our last change
        self.baseline: int | None = None  # sequence number when the backup was taken
        self.restored = False
        self.failed = False      # the backup could not be put back
        self.abandoned = ""      # reason the backup was deliberately not put back
        self.restore_timeout_s = 2.0

    def __enter__(self) -> "ClipboardGuard":
        self.baseline = self.backend.sequence()
        self.snap = self.backend.snapshot()
        return self

    def __exit__(self, *exc) -> None:
        self.restore()

    @property
    def changed(self) -> bool:
        return self._ours is not None

    def mark_ours(self) -> None:
        """Record that the current clipboard content was produced by us (e.g. our Ctrl+C)."""
        self._ours = self.backend.sequence()

    def set_text(self, text: str) -> None:
        ok = self.backend.set_text(text)
        # Even a failed attempt may have emptied the clipboard: the backup must still go back.
        self.mark_ours()
        if not ok:
            raise ClipboardError("could not put the text on the clipboard")

    def abandon(self, reason: str) -> None:
        """Do not restore: the target may still read our text later (it is not responding)."""
        self.abandoned = reason
        self.restored = True
        if self.snap is not None:
            self.backend.discard(self.snap)
        log.warning("clipboard not restored: %s", reason)

    def restore(self) -> bool:
        """Put the backup back. Never raises. False when the user's clipboard could not be restored."""
        if self.restored or self.snap is None:
            return not self.failed
        if self._ours is None:
            self.restored = True
            self.backend.discard(self.snap)
            return True  # we never changed it
        deadline = time.monotonic() + self.restore_timeout_s
        while True:
            try:
                result = self.backend.restore(self.snap, self._ours)
            except ClipboardError as e:  # someone holds the clipboard open; try again shortly
                if time.monotonic() < deadline:
                    time.sleep(0.1)
                    continue
                log.error("clipboard restore failed: %s", e)
                result = "failed"
            except Exception:
                log.exception("clipboard restore failed")
                result = "failed"
            break
        self.restored = True
        if result == "changed":
            log.info("clipboard changed by another program meanwhile; keeping the newer content")
        elif result != "restored":
            self.failed = True
            log.warning("clipboard restore incomplete")
        if result != "restored":
            self.backend.discard(self.snap)
        return not self.failed


# --------------------------------------------------------------------------- Win32 backend

class Win32Clipboard:
    def __init__(self, open_retries: int = 25, retry_delay_s: float = 0.02):
        from .win import api
        self.api = api
        self.open_retries = open_retries
        self.retry_delay_s = retry_delay_s
        self._fmt_cache: dict[str, int] = {}

    # -- helpers
    def _fmt(self, name: str) -> int:
        if name not in self._fmt_cache:
            self._fmt_cache[name] = self.api.RegisterClipboardFormatW(name)
        return self._fmt_cache[name]

    def _open(self):
        api = self.api
        owner = api.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, api.HWND_MESSAGE, None, None, None)
        if not owner:
            # Without an owner window, EmptyClipboard would leave SetClipboardData unable to work.
            raise ClipboardError("could not create a clipboard owner window")
        for _ in range(self.open_retries):
            if api.OpenClipboard(owner):
                return owner
            time.sleep(self.retry_delay_s)
        if owner:
            api.DestroyWindow(owner)
        raise ClipboardError("the clipboard is in use by another program")

    def _close(self, owner) -> None:
        self.api.CloseClipboard()
        # Destroying the owner leaves the (non-delayed) data on the clipboard and means no
        # other program ever has to wait for this thread to answer clipboard messages.
        if owner:
            self.api.DestroyWindow(owner)

    def _alloc(self, data: bytes):
        api = self.api
        h = api.GlobalAlloc(api.GMEM_MOVEABLE, max(len(data), 1))
        if not h:
            return None
        p = api.GlobalLock(h)
        if not p:
            api.GlobalFree(h)
            return None
        ctypes.memmove(p, data, len(data))
        api.GlobalUnlock(h)
        return h

    def _set(self, fmt: int, data: bytes) -> bool:
        h = self._alloc(data)
        if not h:
            return False
        if not self.api.SetClipboardData(fmt, h):
            self.api.GlobalFree(h)
            return False
        return True

    def _name(self, fmt: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        n = self.api.GetClipboardFormatNameW(fmt, buf, 256)
        return buf.value[:n] if n > 0 else ""

    # -- backend interface
    def sequence(self) -> int:
        return int(self.api.GetClipboardSequenceNumber())

    def snapshot(self, timeout_s: float = 5.0) -> Snapshot:
        """Back up the clipboard. Asking other programs to render delayed formats can be slow or hang,
        so this runs on a helper thread; past the timeout the operation is abandoned (nothing changed)."""
        box: dict = {}

        def work():
            try:
                box["snap"] = self._snapshot()
            except BaseException as e:  # noqa: BLE001 - handed to the caller
                box["error"] = e

        t = threading.Thread(target=work, name="LayoutFixer-clipboard-backup", daemon=True)
        t.start()
        t.join(timeout_s)
        if t.is_alive():
            raise ClipboardError("the program that owns the clipboard is not responding")
        if "error" in box:
            raise box["error"]
        return box["snap"]

    def _snapshot(self) -> Snapshot:
        api = self.api
        snap = Snapshot()
        not_copyable = {api.CF_BITMAP, api.CF_PALETTE, api.CF_OWNERDISPLAY, api.CF_DSPBITMAP,
                        api.CF_METAFILEPICT, api.CF_DSPMETAFILEPICT}
        owner = self._open()
        try:
            fmt = 0
            formats = []
            while True:
                fmt = api.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                formats.append(fmt)
            for fmt in formats:
                if fmt in not_copyable or api.CF_PRIVATEFIRST <= fmt <= api.CF_GDIOBJLAST:
                    # CF_BITMAP / CF_METAFILEPICT come back automatically from CF_DIB / CF_ENHMETAFILE.
                    snap.skipped.append(fmt)
                    continue
                h = api.GetClipboardData(fmt)
                if not h:
                    snap.skipped.append(fmt)
                    continue
                if fmt in (api.CF_ENHMETAFILE, api.CF_DSPENHMETAFILE):
                    copy = api.CopyEnhMetaFileW(h, None)
                    if copy:
                        snap.items.append((fmt, "emf", copy))
                    else:
                        snap.skipped.append(fmt)
                    continue
                size = api.GlobalSize(h)
                p = api.GlobalLock(h)
                if not p:
                    snap.skipped.append(fmt)
                    continue
                try:
                    snap.items.append((fmt, "bytes", ctypes.string_at(p, size)))
                finally:
                    api.GlobalUnlock(h)
                if fmt >= 0xC000:
                    snap.names[fmt] = self._name(fmt)
        finally:
            self._close(owner)
        if snap.skipped:
            log.info("clipboard backup: %d format(s) copied, %d left to Windows synthesis or not copyable",
                     len(snap.items), len(snap.skipped))
        return snap

    def restore(self, snap: Snapshot, expected_seq: int | None = None) -> str:
        api = self.api
        owner = self._open()
        ok = True
        written = False
        try:
            # Checked while we hold the clipboard, so nothing can sneak in between check and write.
            if expected_seq is not None and self.sequence() != expected_seq:
                return "changed"
            api.EmptyClipboard()
            written = True
            present = set()
            for fmt, kind, payload in snap.items:
                if kind == "emf":
                    if api.SetClipboardData(fmt, payload):
                        present.add(fmt)
                    else:
                        api.DeleteEnhMetaFile(payload)
                        ok = False
                elif self._set(fmt, payload):  # type: ignore[arg-type]
                    present.add(fmt)
                else:
                    ok = False
            if snap.items:
                # Already in clipboard history from the user's own copy - don't add it twice.
                for name in NO_HISTORY_FORMATS:
                    fmt = self._fmt(name)
                    if fmt not in present:
                        self._set(fmt, (0).to_bytes(4, "little"))
        finally:
            if written:
                snap.items = [i for i in snap.items if i[1] != "emf"]  # ownership passed to Windows
            self._close(owner)
        if snap.skipped:
            log.info("clipboard restore: %d format(s) could not be backed up", len(snap.skipped))
        return "restored" if ok else "failed"

    def discard(self, snap: Snapshot) -> None:
        for _fmt, kind, payload in snap.items:
            if kind == "emf":
                self.api.DeleteEnhMetaFile(payload)
        snap.items = []

    def set_text(self, text: str) -> bool:
        api = self.api
        data = (text + "\0").encode("utf-16-le")
        owner = self._open()
        try:
            api.EmptyClipboard()
            if not self._set(api.CF_UNICODETEXT, data):
                return False
            for name in EXCLUDE_FORMATS:
                self._set(self._fmt(name), (0).to_bytes(4, "little"))
            for name in NO_HISTORY_FORMATS:
                self._set(self._fmt(name), (0).to_bytes(4, "little"))
            return True
        finally:
            self._close(owner)

    def get_text(self) -> str | None:
        api = self.api
        owner = self._open()
        try:
            h = api.GetClipboardData(api.CF_UNICODETEXT)
            if not h:
                return None
            p = api.GlobalLock(h)
            if not p:
                return None
            try:
                return ctypes.wstring_at(p)
            finally:
                api.GlobalUnlock(h)
        finally:
            self._close(owner)
