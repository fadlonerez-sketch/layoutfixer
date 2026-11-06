"""Create build/venv313: Python 3.13 (the version inside the Mac app) with PySide6 6.9.3 and the test tools.

Run with any Python 3.9+ on Windows. Downloads python-build-standalone 3.13.18 (hash-checked) unless
build/py313-win already exists.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "cpython-3.13.18+20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
SHA256 = "7369f7a35f261222a6ac8b3a87c1c88eeebee8af945d85346202591a64038dd3"
URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/" + NAME.replace("+", "%2B")
PACKAGES = ["PySide6-Essentials==6.9.3", "comtypes==1.4.17", "pytest==9.1.1", "pytest-qt==4.5.0"]


def main() -> int:
    home = ROOT / "build" / "py313-win"
    python = home / "python" / "python.exe"
    if not python.exists():
        tar = ROOT / "build" / "mac-cache" / "python" / NAME
        if not tar.exists():
            tar.parent.mkdir(parents=True, exist_ok=True)
            print(f"downloading {NAME}")
            with urllib.request.urlopen(URL, timeout=300) as r:
                tar.write_bytes(r.read())
        if hashlib.sha256(tar.read_bytes()).hexdigest() != SHA256:
            print("checksum mismatch", file=sys.stderr)
            return 1
        home.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar) as t:
            t.extractall(home, filter="data")
    venv = ROOT / "build" / "venv313"
    vpy = venv / "Scripts" / "python.exe"
    if not vpy.exists():
        subprocess.run([str(python), "-m", "venv", str(venv)], check=True)
    subprocess.run([str(vpy), "-m", "pip", "install", "-q", *PACKAGES], check=True)
    print(f"ready: {vpy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
