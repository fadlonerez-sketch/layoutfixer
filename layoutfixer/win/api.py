"""ctypes declarations for the Win32 functions Layout Fixer uses (64-bit safe signatures)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HKL = ctypes.c_void_p
ULONG_PTR = ctypes.c_size_t

# Messages
WM_NULL = 0x0000
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_QUIT = 0x0012
WM_INPUTLANGCHANGEREQUEST = 0x0050
WM_HOTKEY = 0x0312
WM_APP = 0x8000
EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_REPLACESEL = 0x00C2
EM_UNDO = 0x00C7
EM_GETOPTIONS = 0x0400 + 78  # RichEdit only
SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001

# Styles
GWL_STYLE = -16
ES_PASSWORD = 0x0020
ES_READONLY = 0x0800
ES_MULTILINE = 0x0004

# Hotkeys
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Keyboard
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_C, VK_V = 0x43, 0x56
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
MAPVK_VK_TO_VSC = 0
MAPVK_VSC_TO_VK_EX = 3

# Clipboard / memory
CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_LOCALE = 16
CF_DIBV5 = 17
CF_OWNERDISPLAY = 0x0080
CF_DSPBITMAP = 0x0082
CF_DSPMETAFILEPICT = 0x0083
CF_DSPENHMETAFILE = 0x008E
CF_PRIVATEFIRST = 0x0200
CF_GDIOBJLAST = 0x03FF
GMEM_MOVEABLE = 0x0002

# Processes / tokens
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
TokenIntegrityLevel = 25


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND), ("hwndFocus", W.HWND),
                ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND), ("hwndMoveSize", W.HWND),
                ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


def _sig(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


# user32
GetForegroundWindow = _sig(user32.GetForegroundWindow, W.HWND)
GetWindowThreadProcessId = _sig(user32.GetWindowThreadProcessId, W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
GetGUIThreadInfo = _sig(user32.GetGUIThreadInfo, W.BOOL, W.DWORD, ctypes.POINTER(GUITHREADINFO))
GetClassNameW = _sig(user32.GetClassNameW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
GetWindowLongPtrW = _sig(user32.GetWindowLongPtrW, ctypes.c_ssize_t, W.HWND, ctypes.c_int)
IsWindow = _sig(user32.IsWindow, W.BOOL, W.HWND)
IsWindowEnabled = _sig(user32.IsWindowEnabled, W.BOOL, W.HWND)
SendMessageTimeoutW = _sig(user32.SendMessageTimeoutW, LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT,
                           W.UINT, ctypes.POINTER(ULONG_PTR))
SendMessageW = _sig(user32.SendMessageW, LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
PostMessageW = _sig(user32.PostMessageW, W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
GetKeyboardLayout = _sig(user32.GetKeyboardLayout, HKL, W.DWORD)
GetKeyboardLayoutList = _sig(user32.GetKeyboardLayoutList, ctypes.c_int, ctypes.c_int, ctypes.POINTER(HKL))
ActivateKeyboardLayout = _sig(user32.ActivateKeyboardLayout, HKL, HKL, W.UINT)
ToUnicodeEx = _sig(user32.ToUnicodeEx, ctypes.c_int, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_ubyte), W.LPWSTR,
                   ctypes.c_int, W.UINT, HKL)
MapVirtualKeyExW = _sig(user32.MapVirtualKeyExW, W.UINT, W.UINT, W.UINT, HKL)
MapVirtualKeyW = _sig(user32.MapVirtualKeyW, W.UINT, W.UINT, W.UINT)
GetKeyNameTextW = _sig(user32.GetKeyNameTextW, ctypes.c_int, W.LONG, W.LPWSTR, ctypes.c_int)
GetAsyncKeyState = _sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
SendInput = _sig(user32.SendInput, W.UINT, W.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
RegisterHotKey = _sig(user32.RegisterHotKey, W.BOOL, W.HWND, ctypes.c_int, W.UINT, W.UINT)
UnregisterHotKey = _sig(user32.UnregisterHotKey, W.BOOL, W.HWND, ctypes.c_int)
GetMessageW = _sig(user32.GetMessageW, W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
PeekMessageW = _sig(user32.PeekMessageW, W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT)
PostThreadMessageW = _sig(user32.PostThreadMessageW, W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)
OpenClipboard = _sig(user32.OpenClipboard, W.BOOL, W.HWND)
CloseClipboard = _sig(user32.CloseClipboard, W.BOOL)
EmptyClipboard = _sig(user32.EmptyClipboard, W.BOOL)
EnumClipboardFormats = _sig(user32.EnumClipboardFormats, W.UINT, W.UINT)
GetClipboardData = _sig(user32.GetClipboardData, W.HANDLE, W.UINT)
SetClipboardData = _sig(user32.SetClipboardData, W.HANDLE, W.UINT, W.HANDLE)
GetClipboardSequenceNumber = _sig(user32.GetClipboardSequenceNumber, W.DWORD)
RegisterClipboardFormatW = _sig(user32.RegisterClipboardFormatW, W.UINT, W.LPCWSTR)
GetClipboardFormatNameW = _sig(user32.GetClipboardFormatNameW, ctypes.c_int, W.UINT, W.LPWSTR, ctypes.c_int)

# kernel32
GetCurrentThreadId = _sig(kernel32.GetCurrentThreadId, W.DWORD)
GetCurrentProcessId = _sig(kernel32.GetCurrentProcessId, W.DWORD)
GetCurrentProcess = _sig(kernel32.GetCurrentProcess, W.HANDLE)
OpenProcess = _sig(kernel32.OpenProcess, W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
CloseHandle = _sig(kernel32.CloseHandle, W.BOOL, W.HANDLE)
QueryFullProcessImageNameW = _sig(kernel32.QueryFullProcessImageNameW, W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR,
                                  ctypes.POINTER(W.DWORD))
GlobalAlloc = _sig(kernel32.GlobalAlloc, W.HGLOBAL, W.UINT, ctypes.c_size_t)
GlobalLock = _sig(kernel32.GlobalLock, W.LPVOID, W.HGLOBAL)
GlobalUnlock = _sig(kernel32.GlobalUnlock, W.BOOL, W.HGLOBAL)
GlobalSize = _sig(kernel32.GlobalSize, ctypes.c_size_t, W.HGLOBAL)
GlobalFree = _sig(kernel32.GlobalFree, W.HGLOBAL, W.HGLOBAL)

# gdi32
CopyEnhMetaFileW = _sig(gdi32.CopyEnhMetaFileW, W.HANDLE, W.HANDLE, W.LPCWSTR)
DeleteEnhMetaFile = _sig(gdi32.DeleteEnhMetaFile, W.BOOL, W.HANDLE)

# advapi32
OpenProcessToken = _sig(advapi32.OpenProcessToken, W.BOOL, W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE))
GetTokenInformation = _sig(advapi32.GetTokenInformation, W.BOOL, W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD,
                           ctypes.POINTER(W.DWORD))
GetSidSubAuthorityCount = _sig(advapi32.GetSidSubAuthorityCount, ctypes.POINTER(ctypes.c_ubyte), W.LPVOID)
GetSidSubAuthority = _sig(advapi32.GetSidSubAuthority, ctypes.POINTER(W.DWORD), W.LPVOID, W.DWORD)


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = GetClassNameW(hwnd, buf, 256)
    return buf.value[:n] if n > 0 else ""


def window_thread_process(hwnd) -> tuple[int, int]:
    pid = W.DWORD()
    tid = GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return tid, pid.value


def send_message_timeout(hwnd, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 1500) -> int | None:
    """SendMessageTimeout; None when the call failed or timed out (hung or inaccessible window)."""
    result = ULONG_PTR()
    ok = SendMessageTimeoutW(hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG | SMTO_BLOCK, timeout_ms,
                             ctypes.byref(result))
    if not ok:
        return None
    return result.value


def hkl_value(hkl) -> int:
    return int(hkl or 0) & 0xFFFFFFFFFFFFFFFF

HWND_MESSAGE = W.HWND(-3)
CreateWindowExW = _sig(user32.CreateWindowExW, W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
DestroyWindow = _sig(user32.DestroyWindow, W.BOOL, W.HWND)
