"""Which window has the keyboard focus, and can we talk to it."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as W
from dataclasses import dataclass

from . import api


@dataclass(frozen=True)
class FocusInfo:
    hwnd_top: int        # foreground (top-level) window
    hwnd_focus: int      # window with keyboard focus inside it (0 if none / not reported)
    thread_id: int       # GUI thread of the focused window
    pid: int
    class_name: str      # class of hwnd_focus
    process_name: str    # e.g. "chrome.exe" ("" if unknown)
    has_caret: bool

    @property
    def target_hwnd(self) -> int:
        return self.hwnd_focus or self.hwnd_top


def process_name(pid: int) -> str:
    h = api.OpenProcess(api.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = W.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if api.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        api.CloseHandle(h)


def get_focus() -> FocusInfo | None:
    top = api.GetForegroundWindow()
    if not top:
        return None
    tid, pid = api.window_thread_process(top)
    info = api.GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    focus = 0
    caret = False
    if api.GetGUIThreadInfo(tid, ctypes.byref(info)):
        focus = info.hwndFocus or 0
        caret = bool(info.hwndCaret)
    if focus:
        tid, pid = api.window_thread_process(focus)
    hwnd = focus or top
    return FocusInfo(int(top), int(focus or 0), tid, pid, api.class_name(hwnd), process_name(pid), caret)


def _integrity_level(token) -> int | None:
    size = W.DWORD()
    api.GetTokenInformation(token, api.TokenIntegrityLevel, None, 0, ctypes.byref(size))
    if not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not api.GetTokenInformation(token, api.TokenIntegrityLevel, buf, size, ctypes.byref(size)):
        return None
    sid = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_MANDATORY_LABEL.Label.Sid
    count = api.GetSidSubAuthorityCount(sid).contents.value
    return api.GetSidSubAuthority(sid, count - 1).contents.value


def process_integrity(pid: int) -> int | None:
    """Mandatory integrity level RID of a process (0x2000 medium, 0x3000 high), None if unreadable."""
    if pid == os.getpid():
        h = api.GetCurrentProcess()
        close = False
    else:
        h = api.OpenProcess(api.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        close = True
        if not h:
            return None
    try:
        token = W.HANDLE()
        if not api.OpenProcessToken(h, api.TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return _integrity_level(token)
        finally:
            api.CloseHandle(token)
    finally:
        if close:
            api.CloseHandle(h)


def is_more_privileged(pid: int) -> bool:
    """True when Windows (UIPI) would block our messages/keystrokes to that process.

    A process we cannot even query is most likely elevated (or protected).
    """
    ours = process_integrity(os.getpid())
    theirs = process_integrity(pid)
    if theirs is None:
        return True
    return ours is not None and theirs > ours


def wait_responsive(hwnd: int, timeout_s: float = 5.0) -> bool:
    """True once the window's thread handles messages again (False if it is hung / times out)."""
    if not hwnd or not api.IsWindow(hwnd):
        return True
    return api.send_message_timeout(hwnd, api.WM_NULL, 0, 0, int(timeout_s * 1000)) is not None
