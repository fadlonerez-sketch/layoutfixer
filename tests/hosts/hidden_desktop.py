"""Run programs on a separate, never-displayed Windows desktop.

Windows on another desktop are invisible to the user, cannot take their focus and do not
receive their keyboard or mouse input - so a real browser can be driven there through UI
Automation while the user keeps working. Used by the real-Chrome integration tests.
"""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.CreateDesktopW.restype = W.HANDLE
user32.CreateDesktopW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPVOID, W.DWORD, W.DWORD, W.LPVOID]
user32.CloseDesktop.argtypes = [W.HANDLE]
kernel32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
kernel32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
kernel32.CloseHandle.argtypes = [W.HANDLE]
GENERIC_ALL = 0x10000000
CREATE_NO_WINDOW = 0x08000000


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE),
                ("hStdError", W.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


kernel32.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, W.LPVOID, W.LPVOID, W.BOOL, W.DWORD, W.LPVOID, W.LPCWSTR,
                                    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]


class Process:
    def __init__(self, pi: PROCESS_INFORMATION):
        self.pid = pi.dwProcessId
        self.handle = pi.hProcess
        kernel32.CloseHandle(pi.hThread)

    def wait(self, timeout_s: float) -> int | None:
        """Exit code, or None if still running after the timeout."""
        if kernel32.WaitForSingleObject(self.handle, int(timeout_s * 1000)) != 0:
            return None
        code = W.DWORD()
        kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code))
        return code.value

    def kill_tree(self) -> None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.pid)], capture_output=True)
        self.wait(10)
        kernel32.CloseHandle(self.handle)


class HiddenDesktop:
    def __init__(self, name: str):
        self.name = name
        self.handle = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateDesktop failed")
        self.procs: list[Process] = []

    def start(self, command_line: str) -> Process:
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = self.name
        pi = PROCESS_INFORMATION()
        buf = ctypes.create_unicode_buffer(command_line)
        if not kernel32.CreateProcessW(None, buf, None, None, False, CREATE_NO_WINDOW, None, None, ctypes.byref(si),
                                       ctypes.byref(pi)):
            raise OSError(ctypes.get_last_error(), "CreateProcess failed")
        p = Process(pi)
        self.procs.append(p)
        return p

    def close(self) -> None:
        for p in reversed(self.procs):
            p.kill_tree()
        user32.CloseDesktop(self.handle)
