"""macOS shortcuts: parsing, the Cmd+Fn chord logic of the event tap, the manager (no macOS calls).

Events are fed to TapLogic as (type, key code, flags) - the values a Quartz event
tap reports. Whether macOS really delivers the Fn key this way is checked on a Mac.
"""

import pytest

from layoutfixer.hotkeys import HotkeyError, Registration
from layoutfixer.mac import keycodes as K
from layoutfixer.mac.hotkeys import (EV_FLAGS_CHANGED, EV_KEY_DOWN, EV_KEY_UP, EV_LEFT_MOUSE_DOWN,
                                     PERMISSION_MESSAGE, MacHotkey, MacHotkeyManager, TapLogic)
from layoutfixer.config import Settings

CMD, FN, SHIFT, CTRL, OPT = K.FLAG_COMMAND, K.FLAG_FN, K.FLAG_SHIFT, K.FLAG_CONTROL, K.FLAG_OPTION
CMD_KEY, FN_KEY, SHIFT_KEY = 55, 63, 56


def test_parse_cmd_fn():
    hk = MacHotkey.parse("Cmd+Fn")
    assert hk == MacHotkey(CMD | FN, None) and hk.modifier_only and str(hk) == "Cmd+Fn"
    for text in ("⌘+Fn", "Command + Fn", "fn+cmd", "Cmd+Globe"):
        assert MacHotkey.parse(text) == hk


@pytest.mark.parametrize("text, ok", [
    ("Ctrl+Option+Space", True), ("Cmd+Shift+Space", True), ("F5", True), ("Fn+Cmd+K", True),
    ("Fn", False), ("Cmd", False), ("A", False), ("Shift+A", False), ("Option+A", False),
    ("Option+Shift+K", False), ("Cmd+Nope", False), ("Hyper+A", False), ("", False),
])
def test_parse_and_validate(text, ok):
    if ok:
        assert str(MacHotkey.parse(text)) == str(MacHotkey.parse(str(MacHotkey.parse(text))))
    else:
        with pytest.raises(HotkeyError):
            MacHotkey.parse(text)


class Tap:
    def __init__(self, **hotkeys):
        self.fired, self.armed = [], []
        self.logic = TapLogic(self.fired.append, self.armed.append)
        self.logic.hotkeys = {n: MacHotkey.parse(t) for n, t in hotkeys.items()}

    def flags(self, flags, keycode=0):
        return self.logic.handle(EV_FLAGS_CHANGED, keycode, flags)

    def key(self, keycode, flags=0, up=False, autorepeat=False, injected=False):
        return self.logic.handle(EV_KEY_UP if up else EV_KEY_DOWN, keycode, flags, autorepeat, injected)


def test_cmd_fn_fires_once_on_release():
    t = Tap(convert="Cmd+Fn")
    t.flags(CMD, CMD_KEY)
    t.flags(CMD | FN, FN_KEY)
    assert t.armed == ["convert"] and t.fired == []
    t.flags(CMD, FN_KEY)
    assert t.fired == []
    t.flags(0, CMD_KEY)
    assert t.fired == ["convert"]


def test_fn_first_then_cmd_and_device_bits_ignored():
    t = Tap(convert="Cmd+Fn")
    t.flags(FN | 0x100)          # device-dependent bits are masked out
    t.flags(FN | CMD | 0x8)
    t.flags(FN)
    t.flags(0)
    assert t.fired == ["convert"]


def test_capslock_does_not_matter():
    t = Tap(convert="Cmd+Fn")
    t.flags(K.FLAG_CAPSLOCK | CMD)
    t.flags(K.FLAG_CAPSLOCK | CMD | FN)
    t.flags(K.FLAG_CAPSLOCK)
    assert t.fired == ["convert"]


def test_other_key_during_chord_cancels():
    t = Tap(convert="Cmd+Fn")
    t.flags(CMD)
    t.key(K.KC_C, CMD)           # Cmd+C
    t.flags(CMD | FN)
    t.flags(0)
    assert t.fired == []
    t.flags(CMD | FN)
    t.key(K.KEY_NAMES["Left"], CMD | FN)   # Cmd+Fn+Left = Cmd+Home
    t.flags(0)
    assert t.fired == []


def test_mouse_click_during_chord_cancels():
    t = Tap(convert="Cmd+Fn")
    t.flags(CMD | FN)
    t.logic.handle(EV_LEFT_MOUSE_DOWN, 0, CMD | FN)
    t.flags(0)
    assert t.fired == []


def test_extra_modifier_does_not_fire_cmd_fn():
    t = Tap(convert="Cmd+Fn", to_hebrew="Cmd+Shift+Fn")
    t.flags(CMD | FN)
    t.flags(CMD | FN | SHIFT, SHIFT_KEY)
    t.flags(0)
    assert t.fired == ["to_hebrew"]


def test_single_modifiers_never_fire():
    t = Tap(convert="Cmd+Fn")
    for f in (CMD, FN, SHIFT):
        t.flags(f)
        t.flags(0)
    assert t.fired == [] and t.armed == []


def test_next_chord_starts_clean():
    t = Tap(convert="Cmd+Fn")
    t.flags(CMD)
    t.key(K.KC_V, CMD)
    t.flags(0)
    t.flags(CMD | FN)
    t.flags(0)
    assert t.fired == ["convert"]


def test_injected_events_are_ignored():
    t = Tap(convert="Cmd+Fn")
    t.flags(CMD | FN)
    assert t.key(K.KC_V, CMD, injected=True) is False
    t.flags(0)
    assert t.fired == ["convert"]


def test_regular_combo_is_swallowed_with_its_key_up():
    t = Tap(convert_alt="Ctrl+Option+Space")
    space = K.KEY_NAMES["Space"]
    assert t.key(space, CTRL | OPT) is True
    assert t.key(space, CTRL | OPT, autorepeat=True) is True
    assert t.key(space, CTRL | OPT, up=True) is True
    assert t.fired == ["convert_alt"]
    assert t.key(space, CTRL) is False and t.key(space, 0, up=True) is False


def test_fn_flag_on_arrow_keys_is_ignored_unless_wanted():
    t = Tap(a="Ctrl+Option+Left", b="Fn+Cmd+K")
    left = K.KEY_NAMES["Left"]
    assert t.key(left, CTRL | OPT | FN) is True          # macOS adds Fn to arrow keys by itself
    assert t.key(K.KEY_NAMES["K"], CMD) is False          # Fn is part of b: required
    assert t.key(K.KEY_NAMES["K"], CMD | FN) is True
    assert t.fired == ["a", "b"]


def test_recording_reports_chords_and_keys():
    t = Tap(convert="Cmd+Fn")
    got = []
    t.logic.recorder = got.append
    t.flags(CMD | FN)
    t.flags(0)
    assert got == [MacHotkey(CMD | FN, None)] and t.fired == [] and t.armed == []
    assert t.key(K.KEY_NAMES["Space"], CTRL | OPT) is True
    assert str(got[-1]) == "Ctrl+Option+Space"
    t.key(K.KEY_NAMES["A"], OPT)
    assert isinstance(got[-1], HotkeyError)
    t.key(K.KC_ESCAPE)
    t.key(K.KC_DELETE)
    assert got[-2:] == ["cancel", "clear"]
    t.flags(CMD)
    t.flags(0)
    assert len(got) == 5  # a single modifier is not a shortcut


class FakeThread:
    def __init__(self, active=True):
        self.active = active
        self.regs = {}

    def unregister_all(self):
        self.regs.clear()

    def register(self, name, hk):
        self.regs[name] = hk
        return Registration(True, hk) if self.active else Registration(False, hk, 0, PERMISSION_MESSAGE)


def test_manager_main_and_alternative_together():
    th = FakeThread()
    st = MacHotkeyManager(th).apply(Settings(hotkey="Cmd+Fn", fallback_hotkey="Ctrl+Option+Space"))
    assert st.active and not st.fallback_used and set(th.regs) == {"convert", "convert_alt"}
    assert st.summary() == "Shortcut: Cmd+Fn (also Ctrl+Option+Space)"


def test_manager_without_permission_reports_it_once():
    th = FakeThread(active=False)
    st = MacHotkeyManager(th).apply(Settings(hotkey="Cmd+Fn", fallback_hotkey="Ctrl+Option+Space"))
    assert not st.active and st.errors == [PERMISSION_MESSAGE]
    assert set(th.regs) == {"convert", "convert_alt"}  # kept: they work as soon as the tap runs


def test_manager_invalid_main_uses_alternative():
    st = MacHotkeyManager(FakeThread()).apply(Settings(hotkey="Fn", fallback_hotkey="Ctrl+Option+Space"))
    assert st.active and str(st.convert.hotkey) == "Ctrl+Option+Space" and st.errors


def test_manager_disabled():
    th = FakeThread()
    st = MacHotkeyManager(th).apply(Settings(enabled=False, hotkey="Cmd+Fn"))
    assert th.regs == {} and st.summary() == "Disabled"


def test_tap_thread_without_quartz_reports_not_active():
    from layoutfixer.mac.hotkeys import MacHotkeyThread
    th = MacHotkeyThread(lambda n: None, poll_s=0.05)  # no PyObjC here: the tap can never start
    try:
        reg = th.register("convert", MacHotkey.parse("Cmd+Fn"))
        assert not reg.ok and reg.message == PERMISSION_MESSAGE
        assert th.registered() == {"convert": MacHotkey.parse("Cmd+Fn")}
    finally:
        th.stop()
