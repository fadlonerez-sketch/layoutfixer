"""Start at login through a per-user LaunchAgent (~/Library/LaunchAgents; no administrator rights).

The Mac counterpart of startup.py (HKCU\\...\\Run). The agent starts the app
bundle through ``open`` so macOS treats it like a normal app launch.
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

LABEL = "local.layoutfixer.LayoutFixer"


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launch_command() -> list[str]:
    """Command that starts this copy of Layout Fixer in the background."""
    bundle = os.environ.get("LAYOUTFIXER_APP_BUNDLE")  # set by the .app's launcher
    if bundle:
        return ["/usr/bin/open", "-g", "-a", bundle, "--args", "--background"]
    main = Path(__file__).resolve().parents[2] / "main.py"
    return [sys.executable, str(main), "--background"]


def registered_command(path: Path | None = None) -> list[str] | None:
    try:
        with open(path or agent_path(), "rb") as f:
            return list(plistlib.load(f).get("ProgramArguments") or []) or None
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def is_enabled(path: Path | None = None) -> bool:
    return registered_command(path) is not None


def set_enabled(enabled: bool, command: list[str] | None = None, path: Path | None = None) -> None:
    path = path or agent_path()
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = {"Label": LABEL, "ProgramArguments": command or launch_command(), "RunAtLoad": True,
             "ProcessType": "Interactive"}
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        plistlib.dump(plist, f)
    os.replace(tmp, path)


def points_here(path: Path | None = None) -> bool:
    return registered_command(path) == launch_command()
