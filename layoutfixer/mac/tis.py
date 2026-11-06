"""Keyboard layouts through Carbon's Text Input Sources (TIS) API and UCKeyTranslate, via ctypes.

TIS calls must run on the main thread: since macOS 14 TSM aborts the process
(dispatch_assert_queue) when they come from another thread. mac/env.py routes
them through mainthread.MainThreadRunner. ``translate`` only reads layout bytes
and runs on any thread.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, c_long, c_ubyte, c_uint16, c_uint32, c_ulong, c_void_p
from dataclasses import dataclass

CF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
CARBON_PATH = "/System/Library/Frameworks/Carbon.framework/Carbon"
CORESERVICES_PATH = "/System/Library/Frameworks/CoreServices.framework/CoreServices"

K_UC_KEY_ACTION_DOWN = 0
K_UC_NO_DEAD_KEYS = 1        # kUCKeyTranslateNoDeadKeysMask
SHIFT_STATE = 0x0200 >> 8    # (shiftKey >> 8) & 0xFF, as UCKeyTranslate wants modifier state


class CFRange(ctypes.Structure):
    _fields_ = [("location", c_long), ("length", c_long)]


@dataclass(frozen=True)
class SourceInfo:
    id: str
    name: str
    languages: tuple[str, ...]
    is_layout: bool          # a keyboard layout (not an input method / mode)
    enabled: bool            # in the user's input menu
    select_capable: bool

    @property
    def lang(self) -> str | None:
        """"he" / "en" / None from the source's primary language."""
        first = (self.languages[0] if self.languages else "").lower().replace("_", "-").split("-")[0]
        if first in ("he", "iw"):
            return "he"
        if first == "en":
            return "en"
        return None


class _Lib:
    _instance: "_Lib | None" = None

    def __init__(self):
        cf = ctypes.cdll.LoadLibrary(CF_PATH)
        carbon = ctypes.cdll.LoadLibrary(CARBON_PATH)
        self.cf, self.carbon = cf, carbon
        for name, res, args in (
            ("CFRelease", None, [c_void_p]),
            ("CFGetTypeID", c_ulong, [c_void_p]),
            ("CFStringGetTypeID", c_ulong, []),
            ("CFArrayGetTypeID", c_ulong, []),
            ("CFBooleanGetTypeID", c_ulong, []),
            ("CFDataGetTypeID", c_ulong, []),
            ("CFStringGetLength", c_long, [c_void_p]),
            ("CFStringGetCharacters", None, [c_void_p, CFRange, POINTER(c_uint16)]),
            ("CFArrayGetCount", c_long, [c_void_p]),
            ("CFArrayGetValueAtIndex", c_void_p, [c_void_p, c_long]),
            ("CFBooleanGetValue", c_ubyte, [c_void_p]),
            ("CFDataGetLength", c_long, [c_void_p]),
            ("CFDataGetBytePtr", c_void_p, [c_void_p]),
        ):
            f = getattr(cf, name)
            f.restype, f.argtypes = res, args
        for name, res, args in (
            ("TISCreateInputSourceList", c_void_p, [c_void_p, c_ubyte]),
            ("TISCopyCurrentKeyboardInputSource", c_void_p, []),
            ("TISCopyCurrentKeyboardLayoutInputSource", c_void_p, []),
            ("TISGetInputSourceProperty", c_void_p, [c_void_p, c_void_p]),
            ("TISSelectInputSource", ctypes.c_int32, [c_void_p]),
            ("LMGetKbdType", c_ubyte, []),
            ("IsSecureEventInputEnabled", c_ubyte, []),
        ):
            f = getattr(carbon, name)
            f.restype, f.argtypes = res, args
        try:
            uck = carbon.UCKeyTranslate
        except AttributeError:
            uck = ctypes.cdll.LoadLibrary(CORESERVICES_PATH).UCKeyTranslate
        uck.restype = ctypes.c_int32
        uck.argtypes = [c_void_p, c_uint16, c_uint16, c_uint32, c_uint32, c_uint32, POINTER(c_uint32), c_ulong,
                        POINTER(c_ulong), POINTER(c_uint16)]
        self.UCKeyTranslate = uck
        self.k = {name: c_void_p.in_dll(carbon, name).value for name in (
            "kTISPropertyInputSourceID", "kTISPropertyLocalizedName", "kTISPropertyInputSourceLanguages",
            "kTISPropertyUnicodeKeyLayoutData", "kTISPropertyInputSourceType", "kTISTypeKeyboardLayout",
            "kTISPropertyInputSourceCategory", "kTISCategoryKeyboardInputSource",
            "kTISPropertyInputSourceIsEnabled", "kTISPropertyInputSourceIsSelectCapable")}
        self.type_string = cf.CFStringGetTypeID()
        self.type_array = cf.CFArrayGetTypeID()
        self.type_bool = cf.CFBooleanGetTypeID()
        self.type_data = cf.CFDataGetTypeID()

    @classmethod
    def get(cls) -> "_Lib":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- CF -> Python
    def string(self, ref) -> str:
        if not ref or self.cf.CFGetTypeID(ref) != self.type_string:
            return ""
        n = self.cf.CFStringGetLength(ref)
        buf = (c_uint16 * max(n, 1))()
        self.cf.CFStringGetCharacters(ref, CFRange(0, n), buf)
        return bytes(buf)[: 2 * n].decode("utf-16-le", "replace")

    def strings(self, ref) -> tuple[str, ...]:
        if not ref or self.cf.CFGetTypeID(ref) != self.type_array:
            return ()
        return tuple(self.string(self.cf.CFArrayGetValueAtIndex(ref, i)) for i in range(self.cf.CFArrayGetCount(ref)))

    def boolean(self, ref) -> bool:
        return bool(ref) and self.cf.CFGetTypeID(ref) == self.type_bool and bool(self.cf.CFBooleanGetValue(ref))

    def data(self, ref) -> bytes | None:
        if not ref or self.cf.CFGetTypeID(ref) != self.type_data:
            return None
        n = self.cf.CFDataGetLength(ref)
        ptr = self.cf.CFDataGetBytePtr(ref)
        return ctypes.string_at(ptr, n) if ptr and n > 0 else None

    def prop(self, source, key: str):
        return self.carbon.TISGetInputSourceProperty(source, self.k[key])

    def info(self, source) -> SourceInfo:
        return SourceInfo(
            id=self.string(self.prop(source, "kTISPropertyInputSourceID")),
            name=self.string(self.prop(source, "kTISPropertyLocalizedName")),
            languages=self.strings(self.prop(source, "kTISPropertyInputSourceLanguages")),
            is_layout=self.string(self.prop(source, "kTISPropertyInputSourceType")) == self.string(
                self.k["kTISTypeKeyboardLayout"]),
            enabled=self.boolean(self.prop(source, "kTISPropertyInputSourceIsEnabled")),
            select_capable=self.boolean(self.prop(source, "kTISPropertyInputSourceIsSelectCapable")),
        )

    def is_keyboard(self, source) -> bool:
        return self.string(self.prop(source, "kTISPropertyInputSourceCategory")) == self.string(
            self.k["kTISCategoryKeyboardInputSource"])


def _each_source(include_all: bool):
    """(TISInputSourceRef, list) pairs; the refs are valid while the list is alive (caller releases)."""
    lib = _Lib.get()
    arr = lib.carbon.TISCreateInputSourceList(None, 1 if include_all else 0)
    refs = [lib.cf.CFArrayGetValueAtIndex(arr, i) for i in range(lib.cf.CFArrayGetCount(arr))] if arr else []
    return arr, refs


# ---------------------------------------------------------------- main thread only
def list_sources(include_all: bool = False) -> list[SourceInfo]:
    """Keyboard input sources: the enabled ones (input menu), or every installed one."""
    lib = _Lib.get()
    arr, refs = _each_source(include_all)
    try:
        return [lib.info(r) for r in refs if lib.is_keyboard(r)]
    finally:
        if arr:
            lib.cf.CFRelease(arr)


def current_source() -> SourceInfo | None:
    lib = _Lib.get()
    ref = lib.carbon.TISCopyCurrentKeyboardInputSource()
    if not ref:
        return None
    try:
        return lib.info(ref)
    finally:
        lib.cf.CFRelease(ref)


def current_layout() -> SourceInfo | None:
    """The keyboard layout behind the current input source (the same source for plain layouts)."""
    lib = _Lib.get()
    ref = lib.carbon.TISCopyCurrentKeyboardLayoutInputSource()
    if not ref:
        return None
    try:
        return lib.info(ref)
    finally:
        lib.cf.CFRelease(ref)


def layout_data(source_id: str) -> bytes | None:
    """The 'uchr' key table of an installed layout (None for input methods without one)."""
    lib = _Lib.get()
    arr, refs = _each_source(True)
    try:
        for r in refs:
            if lib.string(lib.prop(r, "kTISPropertyInputSourceID")) == source_id:
                return lib.data(lib.prop(r, "kTISPropertyUnicodeKeyLayoutData"))
        return None
    finally:
        if arr:
            lib.cf.CFRelease(arr)


def select(source_id: str) -> bool:
    lib = _Lib.get()
    arr, refs = _each_source(True)
    try:
        for r in refs:
            if lib.string(lib.prop(r, "kTISPropertyInputSourceID")) == source_id:
                return lib.carbon.TISSelectInputSource(r) == 0
        return False
    finally:
        if arr:
            lib.cf.CFRelease(arr)


def keyboard_type() -> int:
    return int(_Lib.get().carbon.LMGetKbdType())


def secure_input() -> bool:
    """True while some app has Secure Event Input on (a focused password field, Terminal's Secure
    Keyboard Entry...)."""
    return bool(_Lib.get().carbon.IsSecureEventInputEnabled())


# ---------------------------------------------------------------- any thread
class KeyTranslator:
    """What each key types on one layout, read from its 'uchr' data with UCKeyTranslate."""

    def __init__(self, data: bytes, kbd_type: int):
        self._buf = ctypes.create_string_buffer(data, len(data))
        self.kbd_type = kbd_type
        self._fn = _Lib.get().UCKeyTranslate

    def char(self, keycode: int, shift: bool) -> str:
        dead = c_uint32(0)
        length = c_ulong(0)
        out = (c_uint16 * 8)()
        status = self._fn(ctypes.cast(self._buf, c_void_p), keycode, K_UC_KEY_ACTION_DOWN,
                          SHIFT_STATE if shift else 0, self.kbd_type, K_UC_NO_DEAD_KEYS, ctypes.byref(dead), 8,
                          ctypes.byref(length), out)
        if status != 0:
            return ""
        return bytes(out)[: 2 * length.value].decode("utf-16-le", "replace")
