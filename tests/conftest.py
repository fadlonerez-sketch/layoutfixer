import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUTFIXER_DATA_DIR", str(tmp_path / "data"))


class Host:
    """A test host process (tests/hosts/*.py) driven over stdin/stdout."""

    def __init__(self, script: str, *args: str):
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)  # the Qt host needs the real Windows platform for UI Automation
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "hosts" / script), *args],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                                     env=env)
        self.info = json.loads(self.proc.stdout.readline())

    def cmd(self, **req):
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture(scope="session")
def win32_host():
    h = Host("win32_edit_host.py")
    yield h
    h.close()


@pytest.fixture(scope="session")
def notepad_host(tmp_path_factory):
    """The hidden Win32 host plus a control of Windows 11 Notepad's editor class (RichEditD2DPT).

    Notepad's private riched20.dll (and msptls.dll) are copied to a temp folder, because a normal
    process may not load DLLs from inside the WindowsApps folder."""
    import shutil
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-AppxPackage Microsoft.WindowsNotepad).InstallLocation"],
                       capture_output=True, text=True, timeout=60)
    location = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    src = Path(location) / "Notepad"
    if not location or not (src / "riched20.dll").exists():
        pytest.skip("Windows 11 Notepad (Store version) is not installed")
    dst = tmp_path_factory.mktemp("notepad_richedit")
    for name in ("riched20.dll", "msptls.dll"):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    h = Host("win32_edit_host.py", str(dst / "riched20.dll"))
    yield h
    h.close()


@pytest.fixture(scope="session")
def qt_host():
    h = Host("qt_text_host.py")
    yield h
    h.close()


@pytest.fixture(scope="session")
def uia():
    from layoutfixer.uia import UiaClient
    return UiaClient()
