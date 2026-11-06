"""Synthetic ⌘C / ⌘V (Quartz CGEvents) and waiting for the user to release the shortcut."""

from __future__ import annotations

import time

from .keycodes import FLAG_COMMAND, INJECTED_MARK, KC_C, KC_V, MODIFIER_FLAGS


def held_modifiers() -> int:
    import Quartz as Q
    return int(Q.CGEventSourceFlagsState(Q.kCGEventSourceStateHIDSystemState)) & MODIFIER_FLAGS


def wait_for_modifier_release(timeout_s: float = 1.5, poll_s: float = 0.01) -> bool:
    """Wait until Cmd/Ctrl/Option/Shift/Fn are physically up. False on timeout."""
    deadline = time.monotonic() + timeout_s
    while held_modifiers():
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)
    return True


def send_cmd_combo(keycode: int) -> bool:
    """Cmd + key, down and up. Only Command is set on the events, so a still-held Fn or Shift
    cannot turn ⌘V into another shortcut. Marked so our own event tap ignores them."""
    import Quartz as Q
    source = Q.CGEventSourceCreate(Q.kCGEventSourceStatePrivate)
    events = []
    for down in (True, False):
        ev = Q.CGEventCreateKeyboardEvent(source, keycode, down)
        if ev is None:
            return False
        Q.CGEventSetFlags(ev, FLAG_COMMAND)
        Q.CGEventSetIntegerValueField(ev, Q.kCGEventSourceUserData, INJECTED_MARK)
        events.append(ev)
    for ev in events:
        Q.CGEventPost(Q.kCGHIDEventTap, ev)
    return True


class MacKeyboard:
    """Real keyboard backend (the engine takes any object with these methods)."""

    def wait_for_release(self) -> bool:
        return wait_for_modifier_release()

    def copy(self) -> bool:
        return send_cmd_combo(KC_C)

    def paste(self) -> bool:
        return send_cmd_combo(KC_V)
