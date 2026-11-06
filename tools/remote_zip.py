"""Read single members of a remote .zip/.whl with HTTP range requests (used to probe wheels cheaply)."""

from __future__ import annotations

import struct
import urllib.request
import zlib


def _get(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])


class RemoteZip:
    def __init__(self, url: str):
        self.url = url
        size = _size(url)
        tail = _get(url, max(0, size - 65536), size - 1)
        eocd = tail.rfind(b"PK\x05\x06")
        if eocd < 0:
            raise ValueError("no end of central directory (zip64 not supported)")
        cd_size, cd_off = struct.unpack_from("<II", tail, eocd + 12)
        cd = _get(url, cd_off, cd_off + cd_size - 1)
        self.members: dict[str, tuple[int, int, int, int]] = {}
        p = 0
        while p < len(cd) and cd[p:p + 4] == b"PK\x01\x02":
            (method, _t, _d, _crc, csize, usize, nlen, xlen, clen, _disk, _ia, _ea,
             lho) = struct.unpack_from("<HHHIIIHHHHHII", cd, p + 10)
            name = cd[p + 46:p + 46 + nlen].decode("utf-8")
            self.members[name] = (lho, csize, usize, method)
            p += 46 + nlen + xlen + clen

    def read(self, name: str) -> bytes:
        lho, csize, _usize, method = self.members[name]
        head = _get(self.url, lho, lho + 29)
        nlen, xlen = struct.unpack_from("<HH", head, 26)
        start = lho + 30 + nlen + xlen
        raw = _get(self.url, start, start + csize - 1)
        return zlib.decompress(raw, -15) if method == 8 else raw
