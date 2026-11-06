"""Keyboard layouts: list installed ones, read their key tables, switch the target window and verify it."""

from __future__ import annotations

import ctypes
import logging
import time

from ..env_types import SwitchResult  # shared with the macOS environment
from . import api

log = logging.getLogger(__name__)

LANG_HEBREW = 0x0D
LANG_ENGLISH = 0x09


def lang_of(hkl) -> str | None:
    """"he" / "en" / None from an HKL (its low word is the language id)."""
    langid = api.hkl_value(hkl) & 0xFFFF
    primary = langid & 0x3FF
    if primary == LANG_HEBREW:
        return "he"
    if primary == LANG_ENGLISH:
        return "en"
    return None


def installed_layouts() -> list[int]:
    n = api.GetKeyboardLayoutList(0, None)
    if n <= 0:
        return []
    arr = (api.HKL * n)()
    n = api.GetKeyboardLayoutList(n, arr)
    return [api.hkl_value(arr[i]) for i in range(n)]


def find_layout(lang: str, layouts: list[int] | None = None) -> int | None:
    """Installed HKL for "he" or "en" (prefers Hebrew/Israel 0x040D and English/US 0x0409)."""
    layouts = installed_layouts() if layouts is None else layouts
    preferred = 0x040D if lang == "he" else 0x0409
    matches = [h for h in layouts if lang_of(h) == lang]
    for h in matches:
        if h & 0xFFFF == preferred:
            return h
    return matches[0] if matches else None


def thread_layout(thread_id: int) -> int:
    return api.hkl_value(api.GetKeyboardLayout(thread_id))


def switch_layout(hwnd_focus, hwnd_top, thread_id: int, lang: str, timeout_s: float = 0.6) -> SwitchResult:
    """Ask the target window to switch its input language, then confirm with GetKeyboardLayout.

    WM_INPUTLANGCHANGEREQUEST is what the language bar itself sends; the target's
    DefWindowProc activates the layout on its own thread, which also becomes the
    system-wide input language because that window has the focus.
    """
    hkl = find_layout(lang)
    if hkl is None:
        return SwitchResult(False, f"The {'Hebrew' if lang == 'he' else 'English'} keyboard layout is not installed")
    before = lang_of(thread_layout(thread_id))
    if before == lang:
        return SwitchResult(True, "already active", before, before)
    targets = [h for h in (hwnd_focus, hwnd_top) if h]
    for i, hwnd in enumerate(dict.fromkeys(targets)):
        if not api.PostMessageW(hwnd, api.WM_INPUTLANGCHANGEREQUEST, 0, hkl):
            log.info("WM_INPUTLANGCHANGEREQUEST post failed (window %d, error %d)", i, ctypes.get_last_error())
            continue
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            after = lang_of(thread_layout(thread_id))
            if after == lang:
                return SwitchResult(True, "switched", before, after)
            time.sleep(0.015)
    after = lang_of(thread_layout(thread_id))
    return SwitchResult(after == lang, "switched" if after == lang else "the window ignored the request", before, after)


SCAN_CODES = tuple(list(range(0x02, 0x0E)) + list(range(0x10, 0x1C)) + list(range(0x1E, 0x2A)) + [0x2B]
                   + list(range(0x2C, 0x36)) + [0x39])


def key_table(hkl: int) -> dict[int, tuple[str, str]]:
    """{scan code: (unshifted, shifted)} as Windows produces them with an *installed* layout.

    Uses ToUnicodeEx with flag 4 (do not change keyboard state) - no input is sent anywhere.
    Dead keys are reported as "dead:<char>". (Deliberately no LoadKeyboardLayout here: loading a
    layout adds it to the user's language switcher for the session.)
    """
    table: dict[int, tuple[str, str]] = {}
    for sc in SCAN_CODES:
        vk = api.MapVirtualKeyExW(sc, api.MAPVK_VSC_TO_VK_EX, hkl)
        pair = []
        for shift in (False, True):
            state = (ctypes.c_ubyte * 256)()
            if shift:
                state[api.VK_SHIFT] = 0x80
                state[0xA0] = 0x80
            buf = ctypes.create_unicode_buffer(8)
            n = api.ToUnicodeEx(vk, sc, state, buf, 8, 4, hkl)
            if n < 0:
                api.ToUnicodeEx(vk, sc, state, buf, 8, 4, hkl)  # flush the dead key
                pair.append("dead:" + buf.value[:1])
            else:
                pair.append(buf.value[:n])
        table[sc] = (pair[0], pair[1])
    return table
