"""Shortcut parsing (pure) and REAL RegisterHotKey registration / conflict detection.

No key presses are simulated with SendInput. Delivery is tested by posting WM_HOTKEY to the
hotkey thread (SIMULATED press). Real registrations use rare combinations, except one brief
Ctrl+Space registration that is released immediately.
"""

import threading

import pytest

from layoutfixer.config import Settings
from layoutfixer.hotkeys import (ERROR_HOTKEY_ALREADY_REGISTERED, MOD_ALT, MOD_CONTROL, MOD_SHIFT, Hotkey,
                                 HotkeyError, HotkeyManager, HotkeyThread)
from layoutfixer.win import api

RARE_A = "Ctrl+Alt+Shift+F24"
RARE_B = "Ctrl+Alt+Shift+F23"
RARE_C = "Ctrl+Alt+Shift+F22"


@pytest.fixture
def threads():
    made = []

    def make(cb=lambda name: None):
        t = HotkeyThread(cb)
        made.append(t)
        return t

    yield make
    for t in made:
        t.stop()


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize("text,mods,vk", [
    ("Ctrl+Space", MOD_CONTROL, 0x20),
    ("ctrl + shift + space", MOD_CONTROL | MOD_SHIFT, 0x20),
    ("Alt+F1", MOD_ALT, 0x70),
    ("F13", 0, 0x7C),
    ("Ctrl+`", MOD_CONTROL, 0xC0),
    ("Control+Q", MOD_CONTROL, 0x51),
])
def test_parse(text, mods, vk):
    hk = Hotkey.parse(text)
    assert (hk.modifiers, hk.vk) == (mods, vk)
    assert Hotkey.parse(str(hk)) == hk


def test_format():
    assert str(Hotkey.parse("shift+ctrl+space")) == "Ctrl+Shift+Space"


@pytest.mark.parametrize("bad", ["", "Ctrl+", "Hyper+A", "Ctrl+NoSuchKey", "A", "Shift+A", "Space",
                                 "Ctrl+Alt+A"])
def test_invalid(bad):
    with pytest.raises(HotkeyError):
        Hotkey.parse(bad)


# ------------------------------------------------------------------ real registration
def test_register_and_unregister_rare_combo(threads):
    t = threads()
    reg = t.register("convert", Hotkey.parse(RARE_A))
    assert reg.ok, reg.message
    assert "convert" in t.registered()
    t.unregister("convert")
    assert t.registered() == {}
    # after unregistering, another owner can take it: proves it was really released
    other = threads()
    assert other.register("x", Hotkey.parse(RARE_A)).ok


def test_conflict_is_detected_not_reported_as_success(threads):
    owner = threads()
    assert owner.register("convert", Hotkey.parse(RARE_B)).ok
    second = threads()
    reg = second.register("convert", Hotkey.parse(RARE_B))
    assert not reg.ok
    assert reg.error == ERROR_HOTKEY_ALREADY_REGISTERED
    assert "already in use" in reg.message


def test_ctrl_space_registration_is_truthful(threads):
    """Ctrl+Space on this PC: either we get it (and then nobody else can), or a conflict is reported."""
    t = threads()
    reg = t.register("convert", Hotkey.parse("Ctrl+Space"))
    try:
        if reg.ok:
            rival = threads()
            assert rival.register("rival", Hotkey.parse("Ctrl+Space")).error == ERROR_HOTKEY_ALREADY_REGISTERED
        else:
            assert reg.error == ERROR_HOTKEY_ALREADY_REGISTERED
    finally:
        t.unregister_all()


def test_manager_falls_back_when_main_shortcut_is_taken(threads):
    blocker = threads()
    assert blocker.register("blocker", Hotkey.parse(RARE_A)).ok
    mgr = HotkeyManager(threads())
    status = mgr.apply(Settings(hotkey=RARE_A, fallback_hotkey=RARE_C))
    assert status.active and status.fallback_used
    assert str(status.convert.hotkey) == RARE_C
    assert "already in use" in status.errors[0]


def test_manager_reports_failure_when_nothing_registers(threads):
    blocker = threads()
    blocker.register("a", Hotkey.parse(RARE_A))
    blocker.register("c", Hotkey.parse(RARE_C))
    status = HotkeyManager(threads()).apply(Settings(hotkey=RARE_A, fallback_hotkey=RARE_C))
    assert not status.active
    assert status.summary().startswith("No shortcut registered")


def test_disabled_registers_nothing(threads):
    t = threads()
    status = HotkeyManager(t).apply(Settings(enabled=False, hotkey=RARE_A))
    assert not status.active and t.registered() == {}
    # and the combination is free for other programs
    assert threads().register("other", Hotkey.parse(RARE_A)).ok


def test_suspend_releases_everything(threads):
    t = threads()
    mgr = HotkeyManager(t)
    assert mgr.apply(Settings(hotkey=RARE_A, to_hebrew_hotkey=RARE_B)).active
    mgr.suspend()
    assert t.registered() == {}


def test_forced_direction_shortcuts(threads):
    t = threads()
    status = HotkeyManager(t).apply(Settings(hotkey=RARE_A, to_hebrew_hotkey=RARE_B, to_english_hotkey=RARE_C))
    assert status.active and status.extra["to_hebrew"].ok and status.extra["to_english"].ok
    assert set(t.registered()) == {"convert", "to_hebrew", "to_english"}


def test_wm_hotkey_is_delivered_to_the_callback(threads):
    got = []
    ev = threading.Event()
    t = threads(lambda name: (got.append(name), ev.set()))
    assert t.register("convert", Hotkey.parse(RARE_A)).ok
    hid = next(i for i, n in t._by_id.items() if n == "convert")
    api.PostThreadMessageW(t._tid, api.WM_HOTKEY, hid, 0)  # what Windows posts on a real press
    assert ev.wait(2) and got == ["convert"]


def test_unknown_hotkey_id_ignored(threads):
    got = []
    t = threads(got.append)
    api.PostThreadMessageW(t._tid, api.WM_HOTKEY, 999, 0)
    t.registered()  # round trip through the queue
    t.unregister_all()
    assert got == []
