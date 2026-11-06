"""Just enough Mach-O to build and check the macOS app bundle on any OS.

* parse thin and universal ("fat") binaries: architectures, file type, linked
  libraries, rpaths, minimum macOS version, exported symbols;
* verify each slice's embedded code signature (the CodeDirectory page hashes),
  which Apple silicon requires before running any code;
* merge an arm64 and an x86_64 binary into one universal binary, as ``lipo
  -create`` does: the slices are copied byte for byte, so their signatures stay valid.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

FAT_MAGIC = 0xCAFEBABE
MH_MAGIC_64 = 0xFEEDFACF
CPU_X86_64 = 0x01000007
CPU_ARM64 = 0x0100000C
ARCH_NAMES = {CPU_X86_64: "x86_64", CPU_ARM64: "arm64"}

LC_SYMTAB = 0x2
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_RPATH = 0x8000001C
LC_REEXPORT_DYLIB = 0x8000001F
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_CODE_SIGNATURE = 0x1D
LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
DYLIB_CMDS = {LC_LOAD_DYLIB: "load", LC_LOAD_WEAK_DYLIB: "weak", LC_REEXPORT_DYLIB: "reexport",
              LC_LOAD_UPWARD_DYLIB: "upward"}
FILETYPES = {2: "execute", 6: "dylib", 8: "bundle"}

CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CSMAGIC_CODEDIRECTORY = 0xFADE0C02
HASHES = {1: ("sha1", 20), 2: ("sha256", 32), 3: ("sha256", 20), 4: ("sha384", 48)}


def is_macho(data: bytes) -> bool:
    if len(data) < 8:
        return False
    if struct.unpack_from(">I", data)[0] == FAT_MAGIC:
        # Java class files share the magic; theirs is followed by a version >= 45.
        return 0 < struct.unpack_from(">I", data, 4)[0] < 20
    return struct.unpack_from("<I", data)[0] == MH_MAGIC_64


@dataclass
class Slice:
    arch: str
    filetype: str
    data: bytes = field(repr=False)
    dylibs: list[tuple[str, str]] = field(default_factory=list)  # (kind, path)
    rpaths: list[str] = field(default_factory=list)
    install_name: str | None = None
    minos: str | None = None
    signature: tuple[int, int] | None = None  # (offset, size) of the embedded signature
    symtab: tuple[int, int, int, int] | None = None

    def exported_symbols(self) -> set[str]:
        """External symbols defined in this image (from the symbol table)."""
        if self.symtab is None:
            return set()
        symoff, nsyms, stroff, strsize = self.symtab
        out = set()
        for i in range(nsyms):
            strx, ntype, _sect, _desc, _value = struct.unpack_from("<IBBHQ", self.data, symoff + 16 * i)
            if ntype & 0x01 and (ntype & 0x0E) == 0x0E:  # N_EXT and N_SECT
                end = self.data.index(b"\0", stroff + strx)
                out.add(self.data[stroff + strx:end].decode("ascii", "replace"))
        return out

    def verify_signature(self) -> str:
        """"" when the code signature's page hashes match the slice, otherwise the problem."""
        if self.signature is None:
            return "not signed"
        off, size = self.signature
        blob = self.data[off:off + size]
        magic, _length, count = struct.unpack_from(">III", blob)
        if magic != CSMAGIC_EMBEDDED_SIGNATURE:
            return "bad signature magic"
        for i in range(count):
            _type, boff = struct.unpack_from(">II", blob, 12 + 8 * i)
            if struct.unpack_from(">I", blob, boff)[0] != CSMAGIC_CODEDIRECTORY:
                continue
            (cd_magic, cd_len, version, flags, hash_off, ident_off, n_special, n_code, code_limit, hash_size,
             hash_type, _platform, page_log2) = struct.unpack_from(">IIIIIIIIIBBBB", blob, boff)
            name, _ = HASHES.get(hash_type, (None, 0))
            if name is None:
                return f"unknown hash type {hash_type}"
            page = 1 << page_log2 if page_log2 else code_limit
            for slot in range(n_code):
                start = slot * page
                chunk = self.data[start:min(start + page, code_limit)]
                want = blob[boff + hash_off + slot * hash_size: boff + hash_off + (slot + 1) * hash_size]
                if hashlib.new(name, chunk).digest()[:hash_size] != want:
                    return f"page {slot} hash mismatch"
            return ""
        return "no code directory"


def _parse_thin(data: bytes) -> Slice:
    magic, cputype, _sub, filetype, ncmds, _sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", data)
    if magic != MH_MAGIC_64:
        raise ValueError("not a 64-bit Mach-O")
    s = Slice(ARCH_NAMES.get(cputype & 0xFFFFFFFF, hex(cputype)), FILETYPES.get(filetype, str(filetype)), data)
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd in DYLIB_CMDS or cmd == LC_ID_DYLIB:
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            raw = data[off + name_off: off + size]
            path = raw.split(b"\0", 1)[0].decode()
            if cmd == LC_ID_DYLIB:
                s.install_name = path
            else:
                s.dylibs.append((DYLIB_CMDS[cmd], path))
        elif cmd == LC_RPATH:
            p_off = struct.unpack_from("<I", data, off + 8)[0]
            s.rpaths.append(data[off + p_off: off + size].split(b"\0", 1)[0].decode())
        elif cmd == LC_CODE_SIGNATURE:
            s.signature = struct.unpack_from("<II", data, off + 8)
        elif cmd == LC_SYMTAB:
            s.symtab = struct.unpack_from("<IIII", data, off + 8)
        elif cmd == LC_BUILD_VERSION:
            _platform, minos = struct.unpack_from("<II", data, off + 8)
            s.minos = f"{minos >> 16}.{(minos >> 8) & 0xFF}"
        elif cmd == LC_VERSION_MIN_MACOSX:
            v = struct.unpack_from("<I", data, off + 8)[0]
            s.minos = f"{v >> 16}.{(v >> 8) & 0xFF}"
        off += size
    return s


def parse(data: bytes) -> list[Slice]:
    if struct.unpack_from(">I", data)[0] == FAT_MAGIC:
        n = struct.unpack_from(">I", data, 4)[0]
        slices = []
        for i in range(n):
            _cpu, _sub, offset, size, _align = struct.unpack_from(">iiIII", data, 8 + 20 * i)
            slices.append(_parse_thin(data[offset:offset + size]))
        return slices
    return [_parse_thin(data)]


def fat_merge(*thin: bytes, align_log2: int = 14) -> bytes:
    """Universal binary from thin binaries of different architectures (like ``lipo -create``)."""
    slices = []
    for data in thin:
        if struct.unpack_from(">I", data)[0] == FAT_MAGIC:
            raise ValueError("already universal")
        cputype, cpusub = struct.unpack_from("<ii", data, 4)
        slices.append((cputype, cpusub, data))
    if len({s[0] for s in slices}) != len(slices):
        raise ValueError("two slices of the same architecture")
    slices.sort(key=lambda s: s[0])  # x86_64 before arm64, as lipo orders them
    align = 1 << align_log2
    offsets, cursor = [], align      # the header is far smaller than one alignment unit
    for _cpu, _sub, data in slices:
        offsets.append(cursor)
        cursor = (cursor + len(data) + align - 1) // align * align
    out = bytearray(struct.pack(">II", FAT_MAGIC, len(slices)))
    for (cputype, cpusub, data), offset in zip(slices, offsets):
        out += struct.pack(">iiIII", cputype, cpusub, offset, len(data), align_log2)
    for (_cpu, _sub, data), offset in zip(slices, offsets):
        out += b"\0" * (offset - len(out))
        out += data
    return bytes(out)


def resolve(dep: str, loader: str, executable: str, rpaths: list[str]) -> list[str]:
    """Candidate bundle-relative paths for a dependency of the image at ``loader`` (POSIX paths)."""
    import posixpath
    loader_dir = posixpath.dirname(loader)
    exe_dir = posixpath.dirname(executable)

    def subst(p: str) -> str:
        if p.startswith("@loader_path"):
            return posixpath.normpath(loader_dir + p[len("@loader_path"):])
        if p.startswith("@executable_path"):
            return posixpath.normpath(exe_dir + p[len("@executable_path"):])
        return p

    if dep.startswith("@rpath/"):
        return [posixpath.normpath(subst(r) + "/" + dep[len("@rpath/"):]) for r in rpaths]
    return [subst(dep)]
