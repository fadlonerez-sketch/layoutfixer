"""Start at login through HKCU\\...\\Run (per user, no administrator rights)."""

from __future__ import annotations

import os
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LayoutFixer"


def launch_command() -> str:
    """Command line that starts this copy of Layout Fixer in the background."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        exe = pythonw
    main = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{exe}" "{main}" --background'


def is_enabled(key_path: str = RUN_KEY, name: str = VALUE_NAME) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            value, _ = winreg.QueryValueEx(k, name)
            return bool(value)
    except OSError:
        return False


def registered_command(key_path: str = RUN_KEY, name: str = VALUE_NAME) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def set_enabled(enabled: bool, command: str | None = None, key_path: str = RUN_KEY, name: str = VALUE_NAME) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command or launch_command())
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass


def points_here(key_path: str = RUN_KEY, name: str = VALUE_NAME) -> bool:
    cmd = registered_command(key_path, name)
    return bool(cmd) and os.path.normcase(cmd) == os.path.normcase(launch_command())
