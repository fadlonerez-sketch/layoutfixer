"""macOS clipboard backend, start-at-login LaunchAgent, main-thread runner and the tray app in Mac mode.

The pasteboard is a fake with NSPasteboard's methods; the app runs on Qt's offscreen platform with
the Mac code paths switched on (IS_MAC) - PyObjC is not available here, so the event tap never starts
and the permission reads as off, which is exactly the first-start state on a Mac.
"""

import threading
import time

import pytest

from layoutfixer.clipboard import ClipboardGuard
from layoutfixer.config import Settings
from layoutfixer.mac import startup as mac_startup
from layoutfixer.mac.clipboard import TEXT_TYPE, TRANSIENT_TYPES, MacClipboard

from fakes import FakeEnv, FakeTarget
from mac_fakes import FakeItem, FakePasteboard


class FakeMacClipboard(MacClipboard):
    def _new_item(self):
        return FakeItem()

    def _data(self, payload: bytes = b""):
        return bytes(payload)


def test_backup_temp_text_and_restore_every_item_and_type():
    pb = FakePasteboard([{"public.png": b"PNG", "public.utf8-plain-text": b"precious"}, {"public.url": b"u"}])
    cb = FakeMacClipboard(pb)
    with ClipboardGuard(cb) as g:
        g.set_text("שלום")
        assert cb.get_text() == "שלום"
        assert all(t in pb.items[0].data for t in TRANSIENT_TYPES)  # clipboard managers skip it
    assert [it.data.get("public.png") for it in pb.items] == [b"PNG", None]
    assert pb.items[0].data[TEXT_TYPE] == b"precious" and pb.items[1].data == {"public.url": b"u"}
    assert g.restored and not g.failed


def test_newer_copy_by_the_user_is_kept():
    pb = FakePasteboard([{TEXT_TYPE: b"old"}])
    cb = FakeMacClipboard(pb)
    with ClipboardGuard(cb) as g:
        g.set_text("temp")
        pb.external_copy("newer")
    assert cb.get_text() == "newer" and not g.failed


def test_empty_pasteboard_restored_empty():
    pb = FakePasteboard()
    cb = FakeMacClipboard(pb)
    with ClipboardGuard(cb) as g:
        g.set_text("temp")
    assert pb.items == [] and cb.get_text() is None


def test_launch_agent(tmp_path, monkeypatch):
    path = tmp_path / "agent.plist"
    monkeypatch.setenv("LAYOUTFIXER_APP_BUNDLE", "/Applications/Layout Fixer.app")
    assert not mac_startup.is_enabled(path)
    mac_startup.set_enabled(True, path=path)
    import plistlib
    plist = plistlib.loads(path.read_bytes())
    assert plist["ProgramArguments"] == ["/usr/bin/open", "-g", "-a", "/Applications/Layout Fixer.app", "--args",
                                         "--background"]
    assert plist["RunAtLoad"] is True and plist["Label"] == mac_startup.LABEL
    assert mac_startup.is_enabled(path) and mac_startup.points_here(path)
    monkeypatch.setenv("LAYOUTFIXER_APP_BUNDLE", "/Users/x/Downloads/Layout Fixer.app")
    assert not mac_startup.points_here(path)  # moved: the app rewrites the agent on its next start
    mac_startup.set_enabled(False, path=path)
    assert not path.exists() and not mac_startup.is_enabled(path)


def test_main_thread_runner(qtbot):
    from layoutfixer.mainthread import MainThreadRunner
    r = MainThreadRunner(timeout_s=2)
    assert r.call(lambda: threading.current_thread() is threading.main_thread())  # direct on the main thread
    box = {}

    def worker():
        box["main"] = r.call(lambda: threading.current_thread() is threading.main_thread())
        try:
            r.call(lambda: 1 / 0)
        except ZeroDivisionError:
            box["raised"] = True
        r.post(lambda: box.setdefault("posted", threading.current_thread() is threading.main_thread()))

    t = threading.Thread(target=worker)
    t.start()
    qtbot.waitUntil(lambda: "posted" in box, timeout=3000)
    t.join(2)
    assert box == {"main": True, "raised": True, "posted": True}


@pytest.fixture
def mac_app(qtbot, monkeypatch, qapp, tmp_path):
    from layoutfixer import app as app_mod
    monkeypatch.setattr(app_mod, "IS_MAC", True)
    monkeypatch.setattr(app_mod, "startup", mac_startup)
    monkeypatch.setattr(mac_startup, "agent_path", lambda: tmp_path / "agent.plist")
    monkeypatch.setattr("layoutfixer.mac.permissions.is_trusted", lambda prompt=False: False)
    monkeypatch.setattr("layoutfixer.mac.permissions.fn_key_action", lambda: "Show Emoji & Symbols")
    opened = []
    monkeypatch.setattr("layoutfixer.mac.permissions.open_settings", lambda url="ax": opened.append(url))
    env = FakeEnv(target=FakeTarget("akuo"))
    a = app_mod.LayoutFixerApp(qapp, Settings(hotkey="Cmd+Fn", fallback_hotkey=""), first_run=False, env=env)
    a._opened = opened
    yield a, env
    a.hotkey_thread.stop()
    a.dispatcher.stop()
    a.tray.hide()
    a.toast.hide()
    if a.settings_window:
        a.settings_window.close()


def test_mac_app_waits_for_permission_and_says_so(mac_app, qtbot):
    a, env = mac_app
    st = a.hotkeys.status
    assert not st.active and "Accessibility" in st.errors[0]
    assert "Accessibility" in a.toast.last_message and a.toast.last_level == "error"
    assert "convert" in a.hotkey_thread.registered()  # kept for when the permission is granted


def test_mac_app_converts_on_chord_and_alternative(mac_app, qtbot):
    a, env = mac_app
    a._on_hotkey("convert")       # what the event tap calls when Cmd+Fn is released
    qtbot.waitUntil(lambda: a.toast.last_message.startswith("Converted"), timeout=3000)
    assert env.target.text == "שלום"
    time.sleep(0.5)               # past the cooldown
    a._on_hotkey("convert_alt")
    qtbot.waitUntil(lambda: env.target.text == "akuo", timeout=3000)


def test_mac_app_tap_start_reapplies_shortcuts(mac_app, qtbot):
    a, _ = mac_app
    a.hotkey_thread.active = True  # as when the tap started after the permission was granted
    a.tap_state_changed.emit(True)
    qtbot.waitUntil(lambda: a.hotkeys.status.active, timeout=3000)
    assert "Cmd+Fn" in a.toast.last_message


def test_mac_settings_window(mac_app, qtbot):
    a, _ = mac_app
    a.show_settings()
    w = a.settings_window
    assert type(w.hotkey).__name__ == "MacHotkeyEdit" and w.hotkey.text() == "Cmd+Fn"
    assert "off" in w.permission.text() and "Do Nothing" in w.fn_note.text()
    w.fallback.setText("Ctrl+Option+Space")
    saved = []
    w.saved.connect(saved.append)
    w._save()
    assert saved and saved[0].fallback_hotkey == "Ctrl+Option+Space"
    w.hotkey.setText("Fn")
    saved.clear()
    w._save()
    assert not saved and "at least two" in w.message.text()


def test_mac_hotkey_edit_records_through_the_tap(qtbot):
    from layoutfixer.mac.hotkeys import MacHotkey
    from layoutfixer.mac.ui import MacHotkeyEdit

    class Recorder:
        cb = None

        def start_recording(self, cb):
            self.cb = cb
            return True

        def stop_recording(self):
            self.cb = None

    rec = Recorder()
    e = MacHotkeyEdit("Ctrl+Option+Space", rec, allow_empty=True)
    qtbot.addWidget(e)
    e.show()
    e.setFocus()
    qtbot.waitUntil(lambda: rec.cb is not None, timeout=2000)
    threading.Thread(target=rec.cb, args=(MacHotkey.parse("Cmd+Fn"),)).start()  # tap thread
    qtbot.waitUntil(lambda: e.text() == "Cmd+Fn", timeout=2000)
    e.setFocus()
    qtbot.waitUntil(lambda: rec.cb is not None, timeout=2000)
    rec.cb("clear")
    qtbot.waitUntil(lambda: e.text() == "", timeout=2000)


def test_boot_script(tmp_path):
    """packaging/mac/__boot__.py, run like the app's launcher runs it, against a stand-in app package."""
    import json
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    res = tmp_path / "Layout Fixer.app" / "Contents" / "Resources"
    pkg = res / "app" / "layoutfixer"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "app.py").write_text(
        "import json, os, sys\n"
        "def main():\n"
        "    print(json.dumps({'argv': sys.argv[1:], 'bundle': os.environ['LAYOUTFIXER_APP_BUNDLE'],\n"
        "                      'path0': sys.path[0]}))\n"
        "    return 3\n")
    boot = root / "packaging" / "mac" / "__boot__.py"
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("PYTHON")}
    env["RESOURCEPATH"] = str(res)
    r = subprocess.run([sys.executable, str(boot), "-psn_0_12345", "--background"], capture_output=True, text=True,
                       env=env, timeout=60)
    assert r.returncode == 3, r.stderr
    out = json.loads(r.stdout)
    assert out["argv"] == ["--background"]
    assert Path(out["bundle"]).name == "Layout Fixer.app"
    assert Path(out["path0"]) == res / "app"
