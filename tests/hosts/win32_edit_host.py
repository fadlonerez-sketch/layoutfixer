"""Test host: a hidden window with standard Edit / RichEdit controls in its own process.

Prints one JSON line with the control handles, then pumps messages until stdin
closes. Never shown, never activated - tests talk to it only with window messages.
Commands on stdin (one per line): "layout" prints the thread's keyboard layout.
With a path to a copy of Windows 11 Notepad's riched20.dll as argument it also creates a
"notepad" control of Notepad's own editor class, RichEditD2DPT.
"""

import ctypes
import json
import sys
import threading
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.LoadLibraryW("msftedit.dll")
user32.CreateWindowExW.restype = W.HWND
user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]

WS_CHILD, WS_POPUP = 0x40000000, 0x80000000
ES_MULTILINE, ES_AUTOVSCROLL, ES_PASSWORD, ES_READONLY = 0x4, 0x40, 0x20, 0x800

top = user32.CreateWindowExW(0, "STATIC", "LayoutFixer test host", WS_POPUP, -32000, -32000, 400, 400,
                             None, None, None, None)
controls = {
    "edit": user32.CreateWindowExW(0, "EDIT", "", WS_CHILD | ES_MULTILINE | ES_AUTOVSCROLL, 0, 0, 300, 200, top,
                                   None, None, None),
    "single": user32.CreateWindowExW(0, "EDIT", "", WS_CHILD, 0, 0, 300, 20, top, None, None, None),
    "rich": user32.CreateWindowExW(0, "RICHEDIT50W", "", WS_CHILD | ES_MULTILINE, 0, 0, 300, 200, top,
                                   None, None, None),
    "password": user32.CreateWindowExW(0, "EDIT", "", WS_CHILD | ES_PASSWORD, 0, 0, 300, 20, top, None, None, None),
    "readonly": user32.CreateWindowExW(0, "EDIT", "", WS_CHILD | ES_READONLY, 0, 0, 300, 20, top, None, None, None),
}
if len(sys.argv) > 1:
    kernel32.LoadLibraryW.restype = W.HMODULE
    if not kernel32.LoadLibraryW(sys.argv[1]):
        raise SystemExit(f"cannot load {sys.argv[1]}: error {ctypes.get_last_error()}")
    controls["notepad"] = user32.CreateWindowExW(0, "RichEditD2DPT", "", WS_CHILD | ES_MULTILINE | ES_AUTOVSCROLL,
                                                 0, 0, 300, 200, top, None, None, None)
tid = kernel32.GetCurrentThreadId()
print(json.dumps({"top": top, "thread": tid, "pid": kernel32.GetCurrentProcessId(), **controls}), flush=True)

WM_APP_LAYOUT = 0x8000 + 7


def stdin_reader():
    for line in sys.stdin:
        if line.strip() == "layout":
            user32.PostThreadMessageW(tid, WM_APP_LAYOUT, 0, 0)
    user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT


threading.Thread(target=stdin_reader, daemon=True).start()
msg = W.MSG()
while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    if msg.message == WM_APP_LAYOUT:
        print(json.dumps({"layout": user32.GetKeyboardLayout(0) or 0}), flush=True)
        continue
    user32.TranslateMessage(ctypes.byref(msg))
    user32.DispatchMessageW(ctypes.byref(msg))
