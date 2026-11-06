"""Global shortcuts on macOS, including modifier-only chords such as Cmd+Fn.

Why an event tap: macOS's hotkey API (Carbon RegisterEventHotKey, what Windows'
RegisterHotKey corresponds to) needs a non-modifier key and has no Fn modifier,
so it cannot register Cmd+Fn at all. A Quartz event tap (CGEventTapCreate) sees
every key event of the login session instead; creating one needs the
Accessibility permission (System Settings > Privacy & Security > Accessibility).

A modifier-only chord fires when all its keys have been released and no other
key or mouse button was pressed in between - so Cmd+C, Cmd+Fn+Left (= Cmd+Home)
or Cmd+click never fire it - and only when exactly its modifiers were held.
Modifier events are never swallowed, so the focused app still sees Cmd and Fn
go down and up (harmless) and macOS still sees the Fn/Globe key: if "Press 🌐
key to" is set to an action in System Settings > Keyboard, macOS may run it too.
Regular combinations (e.g. Ctrl+Option+Space) are swallowed when they match.

Fn is only visible with keyboards that send it to the Mac (built-in MacBook
keyboards, Apple Magic Keyboards). Most third-party keyboards handle their Fn
key internally; there the alternative shortcut from Settings is needed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from ..hotkeys import HotkeyError, HotkeyManager, HotkeyStatus, Registration
from .keycodes import (FLAG_FN, FLAG_OPTION, FLAG_SHIFT, FUNCTION_KEYS, INJECTED_MARK, KC_DELETE, KC_ESCAPE,
                       KC_FORWARD_DELETE, KEY_ALIASES, KEY_NAMES, KEYCODE_TO_NAME, MODIFIER_ALIASES,
                       MODIFIER_FLAGS, MODIFIER_KEYCODES, MODIFIER_NAMES, TYPING_KEYS)

log = logging.getLogger(__name__)

# CGEventType values
EV_LEFT_MOUSE_DOWN, EV_RIGHT_MOUSE_DOWN, EV_OTHER_MOUSE_DOWN = 1, 3, 25
EV_KEY_DOWN, EV_KEY_UP, EV_FLAGS_CHANGED = 10, 11, 12
EV_TAP_DISABLED_BY_TIMEOUT, EV_TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFE, 0xFFFFFFFF
TAP_EVENTS = (EV_LEFT_MOUSE_DOWN, EV_RIGHT_MOUSE_DOWN, EV_OTHER_MOUSE_DOWN, EV_KEY_DOWN, EV_KEY_UP, EV_FLAGS_CHANGED)

NAVIGATION_KEYS = {"Left", "Right", "Up", "Down", "Home", "End", "PageUp", "PageDown", "ForwardDelete"}

PERMISSION_MESSAGE = ("waiting for the Accessibility permission (System Settings > Privacy & Security > "
                      "Accessibility > turn on Layout Fixer)")


@dataclass(frozen=True)
class MacHotkey:
    modifiers: int          # FLAG_* bits
    keycode: int | None     # None: a chord of modifier keys only (Cmd+Fn)

    @classmethod
    def parse(cls, text: str) -> "MacHotkey":
        parts = [p.strip() for p in text.replace(" ", "").split("+")]
        if not text.strip() or any(not p for p in parts):
            raise HotkeyError(f"Invalid shortcut: {text!r}")
        mods = 0
        for p in parts[:-1]:
            m = MODIFIER_ALIASES.get(p.lower())
            if m is None:
                raise HotkeyError(f"Unknown modifier {p!r}")
            mods |= m
        last = parts[-1]
        if last.lower() in MODIFIER_ALIASES:
            hk = cls(mods | MODIFIER_ALIASES[last.lower()], None)
        else:
            name = KEY_ALIASES.get(last.lower()) or next((n for n in KEY_NAMES if n.lower() == last.lower()), None)
            if name is None:
                raise HotkeyError(f"Unknown key {last!r}")
            hk = cls(mods, KEY_NAMES[name])
        hk.validate()
        return hk

    @property
    def key_name(self) -> str:
        if self.keycode is None:
            return ""
        return KEYCODE_TO_NAME.get(self.keycode, f"Key{self.keycode}")

    @property
    def modifier_only(self) -> bool:
        return self.keycode is None

    def validate(self) -> None:
        name = self.key_name
        if self.keycode is None:
            if bin(self.modifiers).count("1") < 2:
                raise HotkeyError("A shortcut of modifier keys only needs at least two of them (e.g. Cmd+Fn)")
            return
        if not self.modifiers and name not in FUNCTION_KEYS:
            raise HotkeyError("A shortcut needs Cmd, Ctrl, Option or Fn (only F-keys work alone)")
        if self.modifiers == FLAG_SHIFT and name in TYPING_KEYS:
            raise HotkeyError("Shift plus a typing key would block normal typing")
        if self.modifiers & FLAG_OPTION and not self.modifiers & ~(FLAG_OPTION | FLAG_SHIFT) and name in TYPING_KEYS:
            raise HotkeyError("Option+key types special characters on a Mac - choose another")

    def __str__(self) -> str:
        order = [n for m, n in MODIFIER_NAMES if self.modifiers & m and m != FLAG_FN]
        if self.modifiers & FLAG_FN:
            order.append("Fn")  # "Cmd+Fn", as it is pressed
        if self.keycode is not None:
            order.append(self.key_name)
        return "+".join(order)


def _mods_match(want: int, have: int) -> bool:
    # macOS sets the Fn flag on arrow / F-key / Home... events by itself: only compare it when wanted.
    if want & FLAG_FN:
        return have == want
    return have & ~FLAG_FN == want


class TapLogic:
    """What the event tap does with each event (pure logic, no macOS calls)."""

    def __init__(self, on_fire: Callable[[str], None], on_armed: Callable[[str], None] | None = None):
        self.on_fire = on_fire
        self.on_armed = on_armed
        self.hotkeys: dict[str, MacHotkey] = {}
        self.recorder: Callable[[object], None] | None = None
        self._swallow_up: set[int] = set()
        self._reset()

    def _reset(self) -> None:
        self._active = False   # a modifier chord is in progress
        self._clean = True     # ...and nothing else was pressed during it
        self._peak = 0         # every modifier held at some point of the chord
        self._armed = False

    def handle(self, etype: int, keycode: int, flags: int, autorepeat: bool = False, injected: bool = False) -> bool:
        """True = swallow the event."""
        if injected:
            return False
        if etype == EV_FLAGS_CHANGED:
            self._flags_changed(flags & MODIFIER_FLAGS)
            return False
        if etype == EV_KEY_DOWN:
            if keycode in MODIFIER_KEYCODES:
                return False
            self._clean = False
            mods = flags & MODIFIER_FLAGS
            if self.recorder is not None:
                self._swallow_up.add(keycode)
                if not autorepeat:
                    self._record_key(mods, keycode)
                return True
            for name, hk in self.hotkeys.items():
                if hk.keycode == keycode and _mods_match(hk.modifiers, mods):
                    self._swallow_up.add(keycode)
                    if not autorepeat:
                        self.on_fire(name)
                    return True
            return False
        if etype == EV_KEY_UP:
            if keycode in self._swallow_up:
                self._swallow_up.discard(keycode)
                return True
            return False
        if etype in (EV_LEFT_MOUSE_DOWN, EV_RIGHT_MOUSE_DOWN, EV_OTHER_MOUSE_DOWN):
            self._clean = False
        return False

    def _flags_changed(self, mods: int) -> None:
        if mods:
            if not self._active:
                self._active, self._clean, self._peak, self._armed = True, True, 0, False
            self._peak |= mods
            if self._clean and not self._armed and self.recorder is None:
                for name, hk in self.hotkeys.items():
                    if hk.keycode is None and hk.modifiers == self._peak:
                        self._armed = True
                        if self.on_armed:
                            self.on_armed(name)
                        break
            return
        if not self._active:
            return
        chord, clean = self._peak, self._clean
        self._reset()
        if not clean:
            return
        if self.recorder is not None:
            if bin(chord).count("1") >= 2:
                self.recorder(MacHotkey(chord, None))
            return
        for name, hk in self.hotkeys.items():
            if hk.keycode is None and hk.modifiers == chord:
                self.on_fire(name)
                return

    def _record_key(self, mods: int, keycode: int) -> None:
        assert self.recorder is not None
        if not mods & ~FLAG_FN and keycode == KC_ESCAPE:
            self.recorder("cancel")
        elif not mods & ~FLAG_FN and keycode in (KC_DELETE, KC_FORWARD_DELETE):
            self.recorder("clear")
        elif keycode not in KEYCODE_TO_NAME:
            self.recorder(HotkeyError("That key can't be used in a shortcut"))
        else:
            if KEYCODE_TO_NAME[keycode] in NAVIGATION_KEYS | FUNCTION_KEYS:
                mods &= ~FLAG_FN  # macOS sets the Fn flag on these keys by itself
            hk = MacHotkey(mods, keycode)
            try:
                hk.validate()
            except HotkeyError as e:
                self.recorder(e)
                return
            self.recorder(hk)


class MacHotkeyThread:
    """Owns the event tap, on its own thread and CFRunLoop. Same interface as hotkeys.HotkeyThread.

    Without the Accessibility permission no tap can be created: registrations are kept but reported
    as not active, the permission is checked again every ``poll_s`` seconds, and ``on_state(True)``
    is called once the tap runs (the app then applies its settings again).
    """

    def __init__(self, on_hotkey: Callable[[str], None], on_armed: Callable[[str], None] | None = None,
                 on_state: Callable[[bool], None] | None = None, trusted: Callable[[], bool] | None = None,
                 poll_s: float = 1.5):
        self._on_hotkey = on_hotkey
        self._on_state = on_state
        self._trusted = trusted
        self.poll_s = poll_s
        self.logic = TapLogic(self._fire, on_armed)
        self._lock = threading.Lock()
        self._by_name: dict[str, MacHotkey] = {}
        self._stop = threading.Event()
        self._loop = None
        self._tap = None
        self._source = None
        self.active = False
        self._thread = threading.Thread(target=self._run, name="LayoutFixer-eventtap", daemon=True)
        self._thread.start()

    # -- public, any thread
    def register(self, name: str, hotkey: MacHotkey) -> Registration:
        with self._lock:
            self._by_name[name] = hotkey
            self.logic.hotkeys = dict(self._by_name)
        if self.active:
            log.info("registered %s = %s", name, hotkey)
            return Registration(True, hotkey)  # type: ignore[arg-type]
        return Registration(False, hotkey, 0, PERMISSION_MESSAGE)  # type: ignore[arg-type]

    def unregister(self, name: str) -> None:
        with self._lock:
            self._by_name.pop(name, None)
            self.logic.hotkeys = dict(self._by_name)

    def unregister_all(self) -> None:
        with self._lock:
            self._by_name.clear()
            self.logic.hotkeys = {}

    def registered(self) -> dict[str, MacHotkey]:
        with self._lock:
            return dict(self._by_name)

    def start_recording(self, callback: Callable[[object], None]) -> bool:
        """Report the next chord / key combination to ``callback`` (tap thread) instead of acting on it."""
        self.logic.recorder = callback
        return self.active

    def stop_recording(self) -> None:
        self.logic.recorder = None

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None:
            try:
                import Quartz
                Quartz.CFRunLoopStop(loop)
            except Exception:
                log.exception("could not stop the event tap run loop")
        self._thread.join(5)

    # -- tap thread
    def _fire(self, name: str) -> None:
        try:
            self._on_hotkey(name)
        except Exception:
            log.exception("hotkey handler failed")

    def _run(self) -> None:
        try:
            import Quartz as Q
        except Exception:
            log.exception("Quartz (PyObjC) is not available - no shortcuts")
            return
        while not self._stop.is_set():
            if self._create_tap(Q):
                break
            self._stop.wait(self.poll_s)
        if self._stop.is_set():
            return
        self.active = True
        log.info("event tap active")
        if self._on_state:
            self._on_state(True)
        try:
            Q.CFRunLoopRun()
        finally:
            self.active = False
            try:
                Q.CGEventTapEnable(self._tap, False)
                Q.CFMachPortInvalidate(self._tap)
            except Exception:
                pass
            log.info("event tap stopped")

    def _create_tap(self, Q) -> bool:
        if self._trusted is not None and not self._trusted():
            return False
        mask = 0
        for t in TAP_EVENTS:
            mask |= 1 << t
        tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionDefault,
                                 mask, self._callback, None)
        if tap is None:
            return False
        source = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
        self._loop = Q.CFRunLoopGetCurrent()
        Q.CFRunLoopAddSource(self._loop, source, Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(tap, True)
        self._tap, self._source = tap, source
        return True

    def _callback(self, proxy, etype, event, refcon):
        try:
            import Quartz as Q
            if etype in (EV_TAP_DISABLED_BY_TIMEOUT, EV_TAP_DISABLED_BY_USER_INPUT):
                log.warning("event tap disabled by macOS (%s); enabling it again",
                            "timeout" if etype == EV_TAP_DISABLED_BY_TIMEOUT else "user input")
                if self._tap is not None:
                    Q.CGEventTapEnable(self._tap, True)
                return event
            keycode = 0
            autorepeat = False
            if etype in (EV_KEY_DOWN, EV_KEY_UP, EV_FLAGS_CHANGED):
                keycode = int(Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode))
                if etype == EV_KEY_DOWN:
                    autorepeat = bool(Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventAutorepeat))
            injected = Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData) == INJECTED_MARK
            if self.logic.handle(etype, keycode, int(Q.CGEventGetFlags(event)), autorepeat, injected):
                return None
        except Exception:
            log.exception("event tap callback failed")
        return event


class MacHotkeyStatus(HotkeyStatus):
    def summary(self) -> str:
        text = super().summary()
        alt = self.extra.get("convert_alt")
        if self.enabled and alt is not None and alt.ok:
            text += f" (also {alt.hotkey})"
        return text


class MacHotkeyManager(HotkeyManager):
    """Main shortcut (default Cmd+Fn) and an optional alternative that works at the same time.

    On Windows the second shortcut is a fallback for when another program owns the first. An event
    tap cannot tell whether another app uses a combination, so on a Mac both are simply active; the
    alternative is meant for keyboards that don't send Fn.
    """

    def apply(self, settings) -> HotkeyStatus:
        self.thread.unregister_all()
        status = MacHotkeyStatus(settings.enabled)
        if settings.enabled:
            for name, text in (("convert", settings.hotkey), ("convert_alt", settings.fallback_hotkey),
                               ("to_hebrew", settings.to_hebrew_hotkey), ("to_english", settings.to_english_hotkey)):
                if not text:
                    continue
                try:
                    reg = self.thread.register(name, MacHotkey.parse(text))
                except HotkeyError as e:
                    status.errors.append(f"{text}: {e}")
                    continue
                if name == "convert":
                    status.convert = reg
                else:
                    status.extra[name] = reg
                if not reg.ok and reg.message not in " ".join(status.errors):
                    status.errors.append(reg.message)
            if status.convert is None and status.extra.get("convert_alt") is not None:
                status.convert = status.extra.pop("convert_alt")
        self.status = status
        return status
