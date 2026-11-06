"""Global shortcuts: parsing "Ctrl+Space" strings and RegisterHotKey on a dedicated message thread.

RegisterHotKey reports a conflict (ERROR_HOTKEY_ALREADY_REGISTERED) when another
program or Windows owns the combination; that is surfaced as a failed
registration, never as success. While a hotkey is registered Windows delivers
the combination only to us; unregistering (disable, quit) gives it back to
the other applications.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable

from .config import Settings

log = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MOD_NAMES = ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))
_MOD_ALIASES = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
                "win": MOD_WIN, "windows": MOD_WIN, "meta": MOD_WIN}

KEY_NAMES: dict[str, int] = {
    "Space": 0x20, "Enter": 0x0D, "Tab": 0x09, "Backspace": 0x08, "Escape": 0x1B, "Insert": 0x2D,
    "Delete": 0x2E, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22, "Left": 0x25, "Up": 0x26,
    "Right": 0x27, "Down": 0x28, "Pause": 0x13, "ScrollLock": 0x91, "CapsLock": 0x14, "PrintScreen": 0x2C,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC,
    ".": 0xBE, "/": 0xBF,
}
KEY_NAMES.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
KEY_NAMES.update({chr(c): c for c in range(ord("0"), ord("9") + 1)})
KEY_NAMES.update({f"F{i}": 0x6F + i for i in range(1, 25)})
KEY_NAMES.update({f"Num{i}": 0x60 + i for i in range(10)})
VK_TO_NAME = {vk: name for name, vk in KEY_NAMES.items()}
_ALIASES = {"esc": "Escape", "del": "Delete", "ins": "Insert", "pgup": "PageUp", "pgdn": "PageDown",
            "return": "Enter", "spacebar": "Space"}
_NO_MODIFIER_OK = {f"F{i}" for i in range(1, 25)} | {"Pause", "ScrollLock"}
_TYPING_KEYS = {n for n in KEY_NAMES if len(n) == 1} | {"Space", "Enter", "Tab", "Backspace"}

ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class HotkeyError(ValueError):
    pass


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int

    @classmethod
    def parse(cls, text: str) -> "Hotkey":
        parts = [p.strip() for p in text.replace(" ", "").split("+")]
        if not text.strip() or any(not p for p in parts):
            raise HotkeyError(f"Invalid shortcut: {text!r}")
        mods = 0
        for p in parts[:-1]:
            m = _MOD_ALIASES.get(p.lower())
            if m is None:
                raise HotkeyError(f"Unknown modifier {p!r}")
            mods |= m
        key = parts[-1]
        name = _ALIASES.get(key.lower()) or next((n for n in KEY_NAMES if n.lower() == key.lower()), None)
        if name is None:
            raise HotkeyError(f"Unknown key {key!r}")
        hk = cls(mods, KEY_NAMES[name])
        hk.validate()
        return hk

    @property
    def key_name(self) -> str:
        return VK_TO_NAME.get(self.vk, f"VK{self.vk:02X}")

    def validate(self) -> None:
        name = self.key_name
        if not self.modifiers and name not in _NO_MODIFIER_OK:
            raise HotkeyError("A shortcut needs Ctrl, Alt or Win (only F-keys, Pause and Scroll Lock work alone)")
        if self.modifiers == MOD_SHIFT and name in _TYPING_KEYS:
            raise HotkeyError("Shift plus a typing key would block normal typing")
        if self.modifiers & MOD_ALT and self.modifiers & MOD_CONTROL and not self.modifiers & (MOD_SHIFT | MOD_WIN) \
                and name in _TYPING_KEYS and name != "Space":
            raise HotkeyError("Ctrl+Alt+key is AltGr on many layouts (Hebrew niqqud, symbols) - choose another")

    def __str__(self) -> str:
        mods = [n for m, n in _MOD_NAMES if self.modifiers & m]
        return "+".join(mods + [self.key_name])


@dataclass(frozen=True)
class Registration:
    ok: bool
    hotkey: Hotkey | None
    error: int = 0
    message: str = ""


def describe_error(code: int) -> str:
    if code == ERROR_HOTKEY_ALREADY_REGISTERED:
        return "already in use by another program or by Windows"
    return ctypes.FormatError(code).strip() if code else "unknown error"


class HotkeyThread:
    """Owns all RegisterHotKey registrations; WM_HOTKEY arrives on this thread's message queue."""

    _WAKE = 0x8000 + 0x21  # WM_APP + n

    def __init__(self, on_hotkey: Callable[[str], None]):
        from .win import api
        self.api = api
        self._on_hotkey = on_hotkey
        self._requests: queue.Queue = queue.Queue()
        self._by_id: dict[int, str] = {}
        self._by_name: dict[str, tuple[int, Hotkey]] = {}
        self._next_id = 1
        self._tid = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="LayoutFixer-hotkeys", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("hotkey thread did not start")

    # -- public, any thread
    def _call(self, *request) -> object:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._requests.put((fut, *request))
        if not self.api.PostThreadMessageW(self._tid, self._WAKE, 0, 0):
            raise RuntimeError("hotkey thread is not running")
        return fut.result(timeout=5)

    def register(self, name: str, hotkey: Hotkey) -> Registration:
        return self._call("register", name, hotkey)  # type: ignore[return-value]

    def unregister(self, name: str) -> None:
        self._call("unregister", name)

    def unregister_all(self) -> None:
        self._call("unregister_all")

    def registered(self) -> dict[str, Hotkey]:
        return {n: hk for n, (_i, hk) in dict(self._by_name).items()}

    def stop(self) -> None:
        if self._thread.is_alive():
            self.api.PostThreadMessageW(self._tid, self.api.WM_QUIT, 0, 0)
            self._thread.join(5)

    # -- hotkey thread
    def _do_register(self, name: str, hotkey: Hotkey) -> Registration:
        self._do_unregister(name)
        hid = self._next_id
        self._next_id += 1
        if self.api.RegisterHotKey(None, hid, hotkey.modifiers | MOD_NOREPEAT, hotkey.vk):
            self._by_id[hid] = name
            self._by_name[name] = (hid, hotkey)
            log.info("registered %s = %s", name, hotkey)
            return Registration(True, hotkey)
        code = ctypes.get_last_error()
        log.warning("could not register %s = %s: %s", name, hotkey, describe_error(code))
        return Registration(False, hotkey, code, describe_error(code))

    def _do_unregister(self, name: str) -> None:
        entry = self._by_name.pop(name, None)
        if entry:
            self.api.UnregisterHotKey(None, entry[0])
            self._by_id.pop(entry[0], None)

    def _drain(self) -> None:
        while True:
            try:
                fut, op, *args = self._requests.get_nowait()
            except queue.Empty:
                return
            try:
                if op == "register":
                    fut.set_result(self._do_register(*args))
                elif op == "unregister":
                    fut.set_result(self._do_unregister(*args))
                else:
                    for n in list(self._by_name):
                        self._do_unregister(n)
                    fut.set_result(None)
            except Exception as e:
                fut.set_exception(e)

    def _run(self) -> None:
        from ctypes import wintypes as W
        api = self.api
        msg = W.MSG()
        api.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create the message queue
        self._tid = api.GetCurrentThreadId()
        self._ready.set()
        try:
            while True:
                r = api.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r in (0, -1):
                    break
                if msg.message == api.WM_HOTKEY and not msg.hWnd:
                    name = self._by_id.get(int(msg.wParam))
                    if name:
                        try:
                            self._on_hotkey(name)
                        except Exception:
                            log.exception("hotkey handler failed")
                elif msg.message == self._WAKE:
                    self._drain()
        finally:
            for n in list(self._by_name):
                self._do_unregister(n)
            self._drain()


@dataclass
class HotkeyStatus:
    enabled: bool
    convert: Registration | None = None
    fallback_used: bool = False
    extra: dict[str, Registration] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.convert and self.convert.ok)

    def summary(self) -> str:
        if not self.enabled:
            return "Disabled"
        if self.active:
            text = f"Shortcut: {self.convert.hotkey}"  # type: ignore[union-attr]
            if self.fallback_used:
                text += " (fallback - the main shortcut is taken)"
            return text
        return "No shortcut registered: " + "; ".join(self.errors)


class HotkeyManager:
    """Applies the shortcut settings: main shortcut, automatic fallback, optional forced directions."""

    def __init__(self, thread: HotkeyThread):
        self.thread = thread
        self.status = HotkeyStatus(False)

    def apply(self, settings: Settings) -> HotkeyStatus:
        self.thread.unregister_all()
        status = HotkeyStatus(settings.enabled)
        if settings.enabled:
            for i, text in enumerate([settings.hotkey, settings.fallback_hotkey]):
                if not text:
                    continue
                try:
                    hk = Hotkey.parse(text)
                except HotkeyError as e:
                    status.errors.append(f"{text}: {e}")
                    continue
                reg = self.thread.register("convert", hk)
                status.convert = reg
                if reg.ok:
                    status.fallback_used = i == 1
                    break
                status.errors.append(f"{hk} is {reg.message}")
            for name, text in (("to_hebrew", settings.to_hebrew_hotkey), ("to_english", settings.to_english_hotkey)):
                if not text:
                    continue
                try:
                    reg = self.thread.register(name, Hotkey.parse(text))
                except HotkeyError as e:
                    status.errors.append(f"{text}: {e}")
                    continue
                status.extra[name] = reg
                if not reg.ok:
                    status.errors.append(f"{reg.hotkey} is {reg.message}")
        self.status = status
        return status

    def suspend(self) -> None:
        """Release every shortcut (e.g. while the user records a new one in Settings)."""
        self.thread.unregister_all()
