"""The macOS text target and environment through the real engine, with simulated macOS (mac_fakes.py).

Simulated: the Accessibility API, input sources, ⌘V and the clipboard. Real: the
engine, AXTarget, MacEnvironment, the key tables, ClipboardPaster/ClipboardGuard.
"""

import pytest

from fakes import FakeClipboard, FakeKeyboard
from layoutfixer.config import Settings
from layoutfixer.converter import Direction
from layoutfixer.engine import Engine
from layoutfixer.mac.ax_target import AXTarget
from layoutfixer.mac.env import PERMISSION_MESSAGE, SECURE_INPUT_MESSAGE, UNSUPPORTED_MESSAGE, MacEnvironment, MacFocus
from layoutfixer.paste import ClipboardPaster
from layoutfixer.targets.base import FieldState, TargetError, Unsupported

from mac_fakes import FakeAX, FakeElement, FakeTIS, paste_into

ORIGINAL = {13: "precious\0".encode("utf-16-le")}


def make_env(element=None, tis=None, ax=None, bundle="com.apple.TextEdit", clipboard=None, keyboard=None):
    clipboard = clipboard or FakeClipboard(ORIGINAL)
    keyboard = keyboard or FakeKeyboard()
    if element is not None:
        keyboard.on_paste = paste_into(element, clipboard)
    env = MacEnvironment(lambda f: f(), lambda f: f(), ax=ax or FakeAX(element), tis=tis or FakeTIS(),
                         clipboard=clipboard, keyboard=keyboard, app_info=lambda pid: ("App", bundle),
                         frontmost_pid=lambda: 100)
    return env


def run(env, force=None, **settings):
    return Engine(env, lambda: Settings(**settings), own_pid=1).run(force)


# ------------------------------------------------------------------ Cocoa fields: AXSelectedText
def test_cocoa_field_whole_text_no_clipboard_and_switch():
    el = FakeElement("akuo' nv eurv?")
    env = make_env(el)
    out = run(env)
    assert out.ok and out.level == "success" and out.strategy == "ax", out.message
    assert el.value == "שלום, מה קורה?"
    assert env.tis.selected == ["com.apple.keylayout.Hebrew"] and env.tis.current == "com.apple.keylayout.Hebrew"
    assert env.clipboard.history == [] and env.keyboard.events == []        # never touched
    assert el.sel == (14, 0)                                                 # caret back where it was


def test_cocoa_only_changed_span_written_and_selection_restored():
    el = FakeElement("Dear team, akuo nv - thanks", sel=(11, 8))
    out = run(make_env(el))
    assert out.ok and el.value == "Dear team, שלום מה - thanks"
    assert el.selected_text_writes == ["שלום מה"]      # only the changed run; "Dear team, " / " - thanks" untouched
    assert el.sel == (11, 8)                           # the same characters stay selected


def test_hebrew_to_english_and_back_is_an_undo():
    el = FakeElement("יקךךם")
    tis = FakeTIS(current="com.apple.keylayout.Hebrew")
    env = make_env(el, tis=tis)
    assert run(env).ok and el.value == "hello" and tis.current == "com.apple.keylayout.ABC"
    env2 = make_env(el, tis=tis)
    assert run(env2).ok and el.value == "יקךךם"


def test_mac_layout_keys_are_used_not_the_windows_ones():
    el = FakeElement("w")
    assert run(make_env(el)).ok and el.value == "׳"   # Mac Hebrew: geresh on W


def test_installed_hebrew_variant_is_used():
    el = FakeElement("abd")
    tis = FakeTIS(enabled=("com.apple.keylayout.ABC", "com.apple.keylayout.Hebrew-QWERTY"))
    assert run(make_env(el, tis=tis)).ok and el.value == "אבד"
    assert tis.current == "com.apple.keylayout.Hebrew-QWERTY"


def test_emoji_offsets_in_utf16_units():
    el = FakeElement("😀 akuo 😀", sel=(3, 4))   # the emoji is 2 units: "akuo" starts at unit 3
    assert run(make_env(el)).ok and el.value == "😀 שלום 😀" and el.sel == (3, 4)


def test_layout_taken_when_chord_went_down_survives_a_globe_switch():
    el = FakeElement("akuo")
    tis = FakeTIS()
    env = make_env(el, tis=tis)
    env.note_chord_armed()                       # Cmd and Fn are down, the keyboard is still on ABC
    tis.current = "com.apple.keylayout.Hebrew"   # macOS acts on the Fn/Globe release: input source switched
    out = run(env)
    assert out.ok and out.direction is Direction.EN_TO_HE and el.value == "שלום"
    assert tis.selected == [] and out.level == "success"   # already on Hebrew: nothing more to switch


def test_switch_seen_only_after_a_few_reads_is_still_confirmed():
    el = FakeElement("akuo")
    tis = FakeTIS()
    tis.switch_delay = 3
    out = run(make_env(el, tis=tis))
    assert out.ok and out.level == "success" and tis.current == "com.apple.keylayout.Hebrew"


def test_switch_that_never_shows_is_reported():
    el = FakeElement("akuo")
    tis = FakeTIS(select_ok=False)
    out = run(make_env(el, tis=tis))
    assert out.ok and el.value == "שלום" and out.level == "warning" and "refused" in out.message


def test_hebrew_not_in_input_menu_converts_but_warns():
    el = FakeElement("akuo")
    tis = FakeTIS(enabled=("com.apple.keylayout.ABC",))
    out = run(make_env(el, tis=tis))
    assert out.ok and el.value == "שלום" and out.level == "warning"
    assert "NOT switched" in out.message and "Input Sources" in out.message


def test_other_layout_active_changes_nothing():
    el = FakeElement("akuo")
    out = run(make_env(el, tis=FakeTIS(enabled=("com.apple.keylayout.Russian",),
                                       current="com.apple.keylayout.Russian")))
    assert not out.ok and "neither English nor Hebrew" in out.message and el.value == "akuo"


def test_forced_direction_reads_the_right_layouts():
    el = FakeElement("שלום")
    out = run(make_env(el), force=Direction.HE_TO_EN)   # keyboard on ABC, text typed in Hebrew
    assert out.ok and el.value == "akuo"


# ------------------------------------------------------------------ Chromium / Electron: paste
def test_chromium_async_selection_then_paste_and_clipboard_restored():
    el = FakeElement("12 akuo", chromium=True, select_delay=3)
    env = make_env(el, bundle="com.google.Chrome")
    out = run(env)
    assert out.ok and el.value == "12 שלום", out.message
    assert el.selected_text_writes == []                        # Chromium: never AXSelectedText
    assert env.keyboard.events == ["ctrl+v"]                    # FakeKeyboard's name for the paste keystroke
    assert env.clipboard.history == ["שלום"]
    assert env.clipboard.formats == ORIGINAL                    # the user's clipboard is back


def test_selection_never_applied_changes_nothing():
    el = FakeElement("akuo", chromium=True, never_select=True)
    env = make_env(el, bundle="com.google.Chrome")
    target = AXTarget(env.ax(), el, ClipboardPaster(env.clipboard, env.keyboard), select_timeout_s=0.05)
    state = target.read()
    with pytest.raises(TargetError, match="did not select"):
        target.replace(state, 0, 4, "שלום")
    assert el.value == "akuo" and env.clipboard.history == [] and env.keyboard.events == []


def test_app_ignoring_ax_selected_text_falls_back_to_paste():
    el = FakeElement("akuo", ignore_selected_text=True)
    env = make_env(el)
    out = run(env)
    assert out.ok and el.value == "שלום" and el.selected_text_writes == ["שלום"]
    assert env.keyboard.events == ["ctrl+v"] and env.clipboard.formats == ORIGINAL


def test_firefox_uses_paste():
    el = FakeElement("akuo")
    env = make_env(el, bundle="org.mozilla.firefox")
    assert run(env).ok and el.value == "שלום" and el.selected_text_writes == []


def test_text_changed_between_read_and_write():
    el = FakeElement("akuo")
    target = AXTarget(FakeAX(el), el, paster=None)
    state = target.read()
    el.value = "akuo!"
    with pytest.raises(TargetError, match="changed"):
        target.replace(state, 0, 4, "שלום")


def test_object_replacement_characters_are_never_written_over():
    el = FakeElement("ak￼uo")
    assert run(make_env(el)).ok
    assert el.value == "של￼ום" and el.selected_text_writes == ["ום", "של"]  # last span first


# ------------------------------------------------------------------ refusals
@pytest.mark.parametrize("kwargs, message", [
    (dict(role="AXSecureTextField"), "Password"),
    (dict(subrole="AXSecureTextField"), "Password"),
    (dict(enabled=False), "disabled"),
    (dict(settable=()), "read-only"),
])
def test_refused_fields(kwargs, message):
    el = FakeElement("akuo", **kwargs)
    out = run(make_env(el))
    assert not out.ok and message in out.message and el.value == "akuo"


def test_no_permission_explains_where_to_turn_it_on():
    el = FakeElement("akuo")
    out = run(make_env(el, ax=FakeAX(el, trusted=False)))
    assert not out.ok and out.message == PERMISSION_MESSAGE


def test_terminal_refused():
    el = FakeElement("akuo")
    out = run(make_env(el, bundle="com.apple.Terminal"))
    assert not out.ok and "Terminal" in out.message and el.value == "akuo"


def test_non_text_element_without_caret_is_unsupported():
    el = FakeElement("akuo", role="AXWebArea", settable=())
    env = make_env(el)
    with pytest.raises(Unsupported) as e:
        env.make_target(MacFocus(100, "App", "com.apple.Safari", "AXWebArea", False, el), Settings())
    assert str(e.value) == UNSUPPORTED_MESSAGE


def test_clipboard_fallback_for_text_without_value():
    el = FakeElement("akuo", role="AXGroup")
    env = make_env(el, bundle="com.example.CustomEditor")
    t = env.make_target(MacFocus(100, "Editor", "com.example.CustomEditor", "AXGroup", True, el), Settings())
    assert t.kind == "clipboard"
    with pytest.raises(Unsupported):
        env.make_target(MacFocus(100, "Editor", "com.example.CustomEditor", "AXGroup", True, el),
                        Settings(clipboard_fallback=False))


def test_finder_never_gets_the_clipboard_fallback():
    el = FakeElement("x", role="AXList")
    env = make_env(el, bundle="com.apple.finder")
    with pytest.raises(Unsupported):
        env.make_target(MacFocus(100, "Finder", "com.apple.finder", "AXList", True, el), Settings())


def test_secure_input_blocks_the_fallback():
    el = FakeElement("akuo", role="AXGroup")
    tis = FakeTIS()
    tis.secure = True
    env = make_env(el, tis=tis)
    with pytest.raises(TargetError) as e:
        env.make_target(MacFocus(100, "X", "com.example.X", "AXGroup", True, el), Settings())
    assert str(e.value) == SECURE_INPUT_MESSAGE


def test_chromium_is_asked_to_expose_its_web_content():
    el = FakeElement("akuo", chromium=True)
    ax = FakeAX(None, element_after_enable=el)       # first answer: no focused text element
    env = make_env(el, ax=ax, bundle="com.google.Chrome")
    out = run(env)
    assert out.ok and el.value == "שלום"
    assert ax.app_attrs == {"AXManualAccessibility": True, "AXEnhancedUserInterface": True}


def test_cocoa_app_is_not_given_enhanced_user_interface():
    el = FakeElement("akuo")
    ax = FakeAX(None, element_after_enable=el)
    assert run(make_env(el, ax=ax, bundle="com.apple.TextEdit")).ok
    assert "AXEnhancedUserInterface" not in ax.app_attrs


def test_read_selection_offsets_that_do_not_line_up():
    el = FakeElement("abc abc", sel=(0, 3))
    ax = FakeAX(el)
    ax_get = ax.get
    ax.get = lambda e, a: "zzz" if a == "AXSelectedText" else ax_get(e, a)
    target = AXTarget(ax, el, paster=None)
    state = target.read()
    assert state == FieldState("zzz", 0, 3, selection_only=True)
