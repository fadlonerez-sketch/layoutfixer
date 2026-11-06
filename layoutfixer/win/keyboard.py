"""Synthetic keystrokes (Ctrl+C / Ctrl+V only) and waiting for the user to release the shortcut."""

from __future__ import annotations

import ctypes
import time

from . import api

# Marks our own synthetic input (dwExtraInfo) so it can be told apart in logs/hooks.
INJECTED_MARK = 0x4C46_5846  # "LFXF"

_MODIFIER_VKS = (api.VK_SHIFT, api.VK_CONTROL, api.VK_MENU, api.VK_LWIN, api.VK_RWIN)


def held_modifiers() -> list[int]:
    return [vk for vk in _MODIFIER_VKS if api.GetAsyncKeyState(vk) & 0x8000]


def wait_for_modifier_release(timeout_s: float = 1.5, poll_s: float = 0.01) -> bool:
    """Wait until Ctrl/Shift/Alt/Win are physically up. False on timeout."""
    deadline = time.monotonic() + timeout_s
    while held_modifiers():
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)
    return True


def _key(vk: int, up: bool) -> api.INPUT:
    inp = api.INPUT()
    inp.type = api.INPUT_KEYBOARD
    inp.u.ki.wVk = vk
    inp.u.ki.wScan = api.MapVirtualKeyW(vk, api.MAPVK_VK_TO_VSC)
    inp.u.ki.dwFlags = api.KEYEVENTF_KEYUP if up else 0
    inp.u.ki.dwExtraInfo = INJECTED_MARK
    return inp


def send_ctrl_combo(vk: int) -> bool:
    """Ctrl down, key down, key up, Ctrl up. True when Windows accepted all four events."""
    seq = (api.INPUT * 4)(_key(api.VK_CONTROL, False), _key(vk, False), _key(vk, True), _key(api.VK_CONTROL, True))
    return api.SendInput(4, seq, ctypes.sizeof(api.INPUT)) == 4


class Keyboard:
    """Real keyboard backend (the engine takes any object with these methods)."""

    def wait_for_release(self) -> bool:
        return wait_for_modifier_release()

    def copy(self) -> bool:
        return send_ctrl_combo(api.VK_C)

    def paste(self) -> bool:
        return send_ctrl_combo(api.VK_V)
