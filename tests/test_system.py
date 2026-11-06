"""Settings file, start-at-login registry entry (test key only), focus/privilege queries, index helpers."""

import json
import os
import winreg

import pytest

from layoutfixer import startup
from layoutfixer.config import Settings, data_dir
from layoutfixer.textindex import from_units, normalize_newlines, to_units
from layoutfixer.win import focus

TEST_KEY = r"Software\LayoutFixerTests\Run"


@pytest.fixture
def run_key():
    yield TEST_KEY
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\LayoutFixerTests")
    except OSError:
        pass


def test_settings_round_trip(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(hotkey="Ctrl+Shift+Space", notify_success=False, max_whole_field_chars=5000)
    s.save(p)
    assert Settings.load(p) == s


def test_settings_defaults_and_bad_values(tmp_path):
    p = tmp_path / "s.json"
    assert Settings.load(p) == Settings()
    p.write_text(json.dumps({"enabled": "yes", "max_whole_field_chars": -5, "hotkey": 3, "unknown": 1}))
    s = Settings.load(p)
    assert s.enabled is True and s.hotkey == "Ctrl+Space" and s.max_whole_field_chars == 100
    p.write_text("{not json")
    assert Settings.load(p) == Settings()


def test_data_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUTFIXER_DATA_DIR", str(tmp_path / "x"))
    assert data_dir() == tmp_path / "x" and data_dir().is_dir()


def test_startup_registry_entry(run_key):
    """REAL registry, in a test key under HKCU (the real Run key is never touched by tests)."""
    assert not startup.is_enabled(run_key)
    startup.set_enabled(True, command='"C:\\x\\LayoutFixer.exe" --background', key_path=run_key)
    assert startup.is_enabled(run_key)
    assert startup.registered_command(run_key) == '"C:\\x\\LayoutFixer.exe" --background'
    startup.set_enabled(False, key_path=run_key)
    assert not startup.is_enabled(run_key)
    startup.set_enabled(False, key_path=run_key)  # idempotent


def test_launch_command_from_source():
    cmd = startup.launch_command()
    assert "--background" in cmd and "main.py" in cmd and "pythonw.exe" in cmd.lower()


def test_own_process_integrity_and_privilege():
    level = focus.process_integrity(os.getpid())
    assert level is not None and level >= 0x2000
    assert not focus.is_more_privileged(os.getpid())


def test_system_process_counts_as_blocked():
    assert focus.is_more_privileged(4)  # the System process cannot be queried from a normal process


def test_get_focus_returns_foreground_info():
    info = focus.get_focus()  # read-only query of whatever is in front; nothing is changed
    if info is not None:
        assert info.hwnd_top and info.thread_id and info.pid


@pytest.mark.parametrize("crlf", [False, True])
def test_index_round_trip(crlf):
    text = "a😀\r\nb\nc😀"
    for i in range(len(text) + 1):
        if crlf and text[i - 1:i + 1] == "\r\n":
            continue
        assert from_units(text, to_units(text, i, crlf), crlf) == i


def test_units():
    assert to_units("😀a", 1) == 2
    assert to_units("a\r\nb", 3, True) == 2
    assert to_units("a\r\nb", 3, False) == 3
    assert normalize_newlines("a\r\nb\rc\n") == "a\nb\nc\n"


def test_settings_with_bom(tmp_path):
    p = tmp_path / "s.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"enabled": False}).encode())
    assert Settings.load(p).enabled is False
