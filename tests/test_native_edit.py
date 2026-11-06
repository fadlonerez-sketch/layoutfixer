"""REAL WINDOWS: standard Edit and RichEdit controls in another process, changed with window messages.

The host window is hidden and never focused; no keystrokes and no clipboard are involved
(that is how the native strategy works in production too).
"""

import ctypes

import pytest

from layoutfixer.config import Settings
from layoutfixer.converter import Direction
from layoutfixer.engine import Engine
from layoutfixer.targets.base import TargetError
from layoutfixer.targets.native_edit import NativeEditTarget, is_native_edit_class
from layoutfixer.textindex import from_units, to_units
from layoutfixer.win import api, layouts
from layoutfixer.win.focus import FocusInfo
from layoutfixer.win_env import WindowsEnvironment

CLASSES = {"edit": "Edit", "rich": "RICHEDIT50W", "notepad": "RichEditD2DPT"}


def put(hwnd, text, sel=None):
    buf = ctypes.create_unicode_buffer(text)
    assert api.send_message_timeout(hwnd, api.WM_SETTEXT, 0, ctypes.addressof(buf))
    if sel is not None:
        api.send_message_timeout(hwnd, api.EM_SETSEL, *sel)


def get(hwnd):
    n = api.send_message_timeout(hwnd, api.WM_GETTEXTLENGTH)
    buf = ctypes.create_unicode_buffer(n + 2)
    c = api.send_message_timeout(hwnd, api.WM_GETTEXT, n + 2, ctypes.addressof(buf))
    return ctypes.wstring_at(ctypes.addressof(buf), c)


def get_sel(hwnd):
    s, e = ctypes.c_uint32(), ctypes.c_uint32()
    api.send_message_timeout(hwnd, api.EM_GETSEL, ctypes.addressof(s), ctypes.addressof(e))
    return s.value, e.value


class Keys:
    def wait_for_release(self):
        return True


class NativeEnv(WindowsEnvironment):
    """The real environment, with focus pointed at the host control (tests cannot focus windows)."""

    def __init__(self, info, name, lang):
        super().__init__()
        self.lang = lang  # None: the host thread's real keyboard layout
        self.keyboard = Keys()
        tid, pid = api.window_thread_process(info[name])
        self.f = FocusInfo(info["top"], info[name], tid, pid, CLASSES.get(name, "Edit"), "python.exe", True)

    def focus(self):
        return self.f

    def current_lang(self, f):
        return self.lang or super().current_lang(f)


def engine_for(win32_host, name, lang="en", **settings):
    return Engine(NativeEnv(win32_host.info, name, lang), lambda: Settings(**settings))


@pytest.mark.parametrize("name", ["edit", "rich"])
def test_whole_field_converted_and_caret_kept(win32_host, name):
    h = win32_host.info[name]
    put(h, "akuo' nv eurv?", (5, 5))
    out = engine_for(win32_host, name, switch_layout=False).run()
    assert out.ok and out.level == "success", out
    assert get(h) == "שלום, מה קורה?"
    assert get_sel(h) == (5, 5)


@pytest.mark.parametrize("name", ["edit", "rich"])
def test_only_selection_converted(win32_host, name):
    h = win32_host.info[name]
    text = "keep this akuo and this"
    put(h, text, (10, 14))
    out = engine_for(win32_host, name, switch_layout=False).run()
    assert out.ok, out
    assert get(h) == "keep this שלום and this"
    assert get_sel(h) == (10, 14)


@pytest.mark.parametrize("name", ["edit", "rich"])
def test_multiline_with_emoji_and_crlf(win32_host, name):
    h = win32_host.info[name]
    text = "first line 😀\r\nakuo nv\r\nlast 😀 line"
    put(h, text)
    state = NativeEditTarget(h, CLASSES[name]).read()
    assert state.text == text
    a = text.index("akuo")
    b = a + len("akuo nv")
    rich = name == "rich"
    put(h, text, (to_units(text, a, rich), to_units(text, b, rich)))
    out = engine_for(win32_host, name, switch_layout=False).run()
    assert out.ok, out
    assert get(h) == "first line 😀\r\nשלום מה\r\nlast 😀 line"


@pytest.mark.parametrize("name", ["edit", "rich"])
def test_selection_offsets_round_trip(win32_host, name):
    h = win32_host.info[name]
    text = "a😀b\r\nc😀d"
    put(h, text)
    rich = name == "rich"
    for i in range(len(text) + 1):
        if text[i - 1:i + 1] == "\r\n" and rich:
            continue  # no position between CR and LF in RichEdit
        u = to_units(text, i, rich)
        api.send_message_timeout(h, api.EM_SETSEL, u, u)
        st = NativeEditTarget(h, CLASSES[name]).read()
        assert st.sel_start == i == from_units(text, u, rich)


def test_mixed_field_hebrew_letters_have_no_us_key(win32_host):
    h = win32_host.info["edit"]
    put(h, "שלום לכולם akuo")
    eng = engine_for(win32_host, "edit", switch_layout=False)
    assert eng.run().ok
    assert get(h) == "שלום לכולם שלום"


def test_reverse_direction(win32_host):
    h = win32_host.info["edit"]
    put(h, "יקךךםת 'םרךגץ")
    assert engine_for(win32_host, "edit", "he", switch_layout=False).run().ok
    assert get(h) == "hello, world."


def test_password_field_refused(win32_host):
    h = win32_host.info["password"]
    put(h, "akuo")
    with pytest.raises(TargetError, match="Password"):
        NativeEditTarget(h, "Edit").read()


def test_readonly_field_refused(win32_host):
    h = win32_host.info["readonly"]
    put(h, "akuo")
    with pytest.raises(TargetError, match="read-only"):
        NativeEditTarget(h, "Edit").read()
    assert get(h) == "akuo"


def test_text_changed_between_read_and_write_is_refused(win32_host):
    h = win32_host.info["edit"]
    put(h, "akuo")
    t = NativeEditTarget(h, "Edit")
    state = t.read()
    put(h, "something new")
    with pytest.raises(TargetError, match="changed"):
        t.replace(state, 0, 4, "שלום")
    assert get(h) == "something new"


def test_change_is_undoable_in_the_app(win32_host):
    h = win32_host.info["edit"]
    put(h, "akuo")
    api.send_message_timeout(h, 0x00CD)  # EM_EMPTYUNDOBUFFER
    assert engine_for(win32_host, "edit", switch_layout=False).run().ok
    assert get(h) == "שלום"
    api.send_message_timeout(h, api.EM_UNDO)
    assert get(h) == "akuo"


def test_empty_field(win32_host):
    h = win32_host.info["single"]
    put(h, "")
    out = engine_for(win32_host, "single", switch_layout=False).run()
    assert not out.ok and "empty" in out.message


def test_too_long_without_selection(win32_host):
    h = win32_host.info["edit"]
    put(h, "akuo " * 100)
    out = engine_for(win32_host, "edit", switch_layout=False, max_whole_field_chars=100).run()
    assert not out.ok and "select the part" in out.message
    assert get(h) == "akuo " * 100


def test_converts_and_switches_the_windows_input_language(win32_host):
    """REAL layout switch: the host thread's input language becomes Hebrew, then English."""
    if not (layouts.find_layout("he") and layouts.find_layout("en")):
        pytest.skip("needs both Hebrew and English layouts")
    h = win32_host.info["edit"]
    eng = engine_for(win32_host, "edit", lang=None)  # direction from the real layout of the host thread
    tid = eng.env.f.thread_id
    layouts.switch_layout(h, win32_host.info["top"], tid, "en")
    put(h, "akuo")
    out = eng.run()
    assert out.ok and out.level == "success", out
    assert get(h) == "שלום"
    assert layouts.lang_of(layouts.thread_layout(tid)) == "he"
    out = eng.run()  # pressing again converts back and switches back
    assert out.ok and get(h) == "akuo"
    assert layouts.lang_of(layouts.thread_layout(tid)) == "en"
    assert out.direction is Direction.HE_TO_EN


def test_class_detection():
    for c in ["Edit", "RICHEDIT50W", "RichEditD2DPT", "RichEdit20W", "WindowsForms10.EDIT.app.0.141b42a_r6_ad1",
              "TMemo"]:
        assert is_native_edit_class(c)
    for c in ["Chrome_WidgetWin_1", "Static", "Button", "MozillaWindowClass"]:
        assert not is_native_edit_class(c)


def test_routing_native_edit_and_terminals(win32_host):
    from layoutfixer.targets.base import Unsupported
    env = WindowsEnvironment()
    tid, pid = api.window_thread_process(win32_host.info["edit"])
    f = FocusInfo(win32_host.info["top"], win32_host.info["edit"], tid, pid, "Edit", "python.exe", True)
    assert isinstance(env.make_target(f, Settings()), NativeEditTarget)
    term = FocusInfo(1, 2, tid, pid, "Windows.UI.Input.InputSite.WindowClass", "windowsterminal.exe", True)
    with pytest.raises(Unsupported, match="Terminal"):
        env.make_target(term, Settings())
    conhost = FocusInfo(1, 2, tid, pid, "ConsoleWindowClass", "conhost.exe", True)
    with pytest.raises(Unsupported):
        env.make_target(conhost, Settings())


def test_ignored_replace_does_not_undo_users_edit(win32_host, monkeypatch):
    """If the control silently ignores EM_REPLACESEL, EM_UNDO must not be sent (it would undo the user)."""
    h = win32_host.info["edit"]
    put(h, "akuo")
    t = NativeEditTarget(h, "Edit")
    state = t.read()
    real_send = t._send
    sent = []

    def send(msg, wparam=0, lparam=0):
        sent.append(msg)
        if msg == api.EM_REPLACESEL:
            return 0  # pretend the control ignored it
        return real_send(msg, wparam, lparam)

    monkeypatch.setattr(t, "_send", send)
    with pytest.raises(TargetError, match="nothing was changed"):
        t.replace(state, 0, 4, "שלום")
    assert api.EM_UNDO not in sent and get(h) == "akuo"


def test_wait_responsive_real_window(win32_host):
    from layoutfixer.win.focus import wait_responsive
    assert wait_responsive(win32_host.info["edit"], 2)
    assert wait_responsive(0)


# ------------------------------------------- Windows 11 Notepad's editor control (REAL class, hidden host)
def test_notepad_editor_class_is_handled_natively(notepad_host):
    h = notepad_host.info["notepad"]
    assert h and api.class_name(h) == "RichEditD2DPT" and is_native_edit_class(api.class_name(h))


@pytest.mark.parametrize("text, sel, expected", [
    ("akuo' nv eurv?", (3, 3), "שלום, מה קורה?"),                    # whole field, caret kept
    ("keep akuo keep", (5, 9), "keep שלום keep"),                      # selection only
    ("line one\r\nakuo nv\r\nlast", (0, 0), "ךןמק םמק\r\nשלום מה\r\nךשדא"),  # line breaks
])
def test_notepad_editor_whole_field_and_selection(notepad_host, text, sel, expected):
    h = notepad_host.info["notepad"]
    put(h, text, sel)
    out = engine_for(notepad_host, "notepad", switch_layout=False).run()
    assert out.ok and out.level == "success", out
    assert get(h) == expected
    assert get_sel(h) == sel


def test_notepad_editor_reverse_and_undo(notepad_host):
    h = notepad_host.info["notepad"]
    put(h, "יקךךם")
    api.send_message_timeout(h, 0x00CD)  # EM_EMPTYUNDOBUFFER
    assert engine_for(notepad_host, "notepad", "he", switch_layout=False).run().ok
    assert get(h) == "hello"
    api.send_message_timeout(h, api.EM_UNDO)
    assert get(h) == "יקךךם"


def test_notepad_editor_converts_and_switches_layout(notepad_host):
    """REAL layout switch on the thread that owns the Notepad-class control."""
    if not (layouts.find_layout("he") and layouts.find_layout("en")):
        pytest.skip("needs both Hebrew and English layouts")
    h = notepad_host.info["notepad"]
    eng = engine_for(notepad_host, "notepad", lang=None)
    tid = eng.env.f.thread_id
    layouts.switch_layout(h, notepad_host.info["top"], tid, "en")
    put(h, "akuo")
    out = eng.run()
    assert out.ok and out.level == "success", out
    assert get(h) == "שלום" and layouts.lang_of(layouts.thread_layout(tid)) == "he"
    out = eng.run()
    assert out.ok and get(h) == "akuo" and layouts.lang_of(layouts.thread_layout(tid)) == "en"
