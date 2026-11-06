"""REAL UI Automation against Qt text widgets in another process (off-screen, never focused).

Reading, selecting and verifying go through real UI Automation. The Ctrl+V keystroke and the
clipboard are SIMULATED (FakeKeyboard / FakeClipboard): the fake "paste" asks the host to insert
the fake clipboard's text at its selection, which is what a real Ctrl+V does.
"""

import pytest

from fakes import FakeClipboard, FakeKeyboard
from layoutfixer.config import Settings
from layoutfixer.converter import Direction, convert
from layoutfixer.engine import Engine
from layoutfixer.paste import ClipboardPaster
from layoutfixer.targets.base import TargetError, Unsupported
from layoutfixer.targets.uia_target import UiaTarget

UIA_NamePropertyId = 30005
ORIGINAL = {13: "user's clipboard\0".encode("utf-16-le"), 49999: b"\x01\x02private"}


def element(uia, qt_host, name):
    root = uia.element_from_handle(qt_host.info["hwnd"])
    el = root.FindFirst(4, uia.client.CreatePropertyCondition(UIA_NamePropertyId, "lf-" + name))
    assert el, name
    return el


@pytest.fixture
def rig(uia, qt_host):
    def make(widget, text, sel=None, paste_works=True):
        qt_host.cmd(cmd="set", w=widget, text=text)
        if sel:
            qt_host.cmd(cmd="select", w=widget, a=sel[0], b=sel[1])
        clip = FakeClipboard(ORIGINAL)
        keys = FakeKeyboard()
        if paste_works:
            keys.on_paste = lambda: qt_host.cmd(cmd="paste", w=widget, text=clip.get_text())
        paster = ClipboardPaster(clip, keys, verify_timeout_s=1.0)
        target = UiaTarget(uia, element(uia, qt_host, widget), paster)
        return target, clip, keys
    return make


def state(qt_host, widget):
    return qt_host.cmd(cmd="state", w=widget)


def run(target, settings=None, lang="en"):
    class Env:
        keyboard = FakeKeyboard()

        def focus(self):
            from fakes import focus
            return focus()

        def is_blocked(self, f):
            return False

        def current_lang(self, f):
            return lang

        def switch_layout(self, f, l):
            from layoutfixer.win.layouts import SwitchResult
            return SwitchResult(True, "switched")

        def make_target(self, f, s):
            return target

    return Engine(Env(), lambda: settings or Settings()).run()


def test_whole_line_edit(rig, qt_host):
    target, clip, keys = rig("line", "akuo' nv eurv?")
    out = run(target)
    assert out.ok and out.level == "success", out
    assert state(qt_host, "line")["text"] == "שלום, מה קורה?"
    assert keys.events == ["ctrl+v"]
    assert clip.formats == ORIGINAL  # clipboard restored exactly


def test_only_selection_changes(rig, qt_host):
    target, clip, _ = rig("line", "keep akuo keep", sel=(5, 9))
    out = run(target)
    assert out.ok, out
    assert state(qt_host, "line")["text"] == "keep שלום keep"
    assert clip.formats == ORIGINAL


def test_mixed_field_pastes_only_the_changed_span(rig, qt_host):
    target, clip, _ = rig("plain", "שלום לכולם\nmore text akuo")
    out = run(target, lang="en")
    assert out.ok, out
    assert state(qt_host, "plain")["text"] == "שלום לכולם\nmore text akuo".replace("more text akuo", "צםרק אקסא שלום")
    assert clip.history == ["צםרק אקסא שלום"]  # only the changed span went through the clipboard


def test_multiline_with_emoji(rig, qt_host):
    text = "first 😀 line\nakuo nv\nlast"
    target, clip, _ = rig("plain", text)
    out = run(target, lang="en")
    assert out.ok, out
    assert state(qt_host, "plain")["text"] == convert(text, Direction.EN_TO_HE).text


def test_rich_text_edit_reverse(rig, qt_host):
    target, clip, _ = rig("rich", "יקךךםת 'םרךגץ")
    out = run(target, lang="he")
    assert out.ok, out
    assert state(qt_host, "rich")["text"] == "hello, world."
    assert clip.formats == ORIGINAL


def test_paste_ignored_by_app_reports_failure_and_restores_clipboard(rig, qt_host):
    target, clip, _ = rig("line", "akuo", paste_works=False)
    out = run(target)
    assert not out.ok and "did not accept the paste" in out.message
    assert state(qt_host, "line")["text"] == "akuo"
    assert clip.formats == ORIGINAL


def test_clipboard_unavailable_changes_nothing(rig, qt_host):
    target, clip, keys = rig("line", "akuo")
    clip.fail_set = True
    out = run(target)
    assert not out.ok
    assert keys.events == []  # no paste without the text on the clipboard
    assert state(qt_host, "line")["text"] == "akuo"
    assert clip.formats == ORIGINAL


def test_user_copies_during_paste_keeps_newer_clipboard(rig, qt_host):
    target, clip, keys = rig("line", "akuo")
    real_paste = keys.on_paste

    def paste_then_user_copies():
        real_paste()
        clip.external_copy("newer")

    keys.on_paste = paste_then_user_copies
    assert run(target).ok
    assert clip.get_text() == "newer"


def test_readonly_refused(rig, qt_host):
    target, _, keys = rig("readonly", "akuo")
    with pytest.raises(TargetError, match="read-only"):
        target.read()
    assert keys.events == []


def test_password_refused(rig, qt_host):
    target, _, keys = rig("password", "akuo")
    with pytest.raises(TargetError, match="Password"):
        target.read()


def test_selection_read_through_uia(rig, qt_host):
    target, _, _ = rig("plain", "ab\ncd 😀 ef akuo", sel=(12, 16))
    st = target.read()
    assert st.has_selection and st.text[st.sel_start:st.sel_end] == "akuo"


def test_text_changed_after_read_is_refused(rig, qt_host):
    target, _, keys = rig("line", "akuo")
    st = target.read()
    qt_host.cmd(cmd="set", w="line", text="different")
    with pytest.raises(TargetError, match="changed"):
        target.replace(st, 0, 4, "שלום")
    assert keys.events == []


def test_unsupported_element(uia, qt_host):
    root = uia.element_from_handle(qt_host.info["hwnd"])
    t = UiaTarget(uia, root, None)
    with pytest.raises(Unsupported):
        t.read()


def test_embedded_picture_between_words_is_kept(rig, qt_host):
    """Chat apps show emoji as pictures (U+FFFC in the text): only the words around them change."""
    target, clip, _ = rig("rich", "")
    pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    qt_host.cmd(cmd="html", w="rich", html=f"akuo <img src='{pixel}'> nv")
    assert qt_host.cmd(cmd="images", w="rich")["images"] == 1
    out = run(target, lang="en")
    assert out.ok, out
    assert state(qt_host, "rich")["text"] == "שלום ￼ מה"
    assert qt_host.cmd(cmd="images", w="rich")["images"] == 1  # the picture itself survived
    assert sorted(clip.history) == ["מה", "שלום"]  # two separate pastes, none over the picture


def test_document_is_never_replaced_whole(rig, qt_host, monkeypatch):
    """If the exact range can't be selected in a Document control, refuse instead of pasting over it all."""
    target, clip, keys = rig("plain", "שלום akuo")
    real_check = target.check_editable

    def as_document():
        real_check()
        target.control_type = 50030  # UIA_DocumentControlTypeId
    monkeypatch.setattr(target, "check_editable", as_document)
    monkeypatch.setattr(target, "_range_for", lambda *a: None)
    out = run(target, lang="en")
    assert not out.ok and "select the words" in out.message
    assert keys.events == [] and state(qt_host, "plain")["text"] == "שלום akuo"


def test_edit_control_may_fall_back_to_whole_field(rig, qt_host, monkeypatch):
    target, clip, keys = rig("line", "שלום akuo")
    monkeypatch.setattr(target, "_range_for", lambda *a: None)
    out = run(target, lang="en")
    assert out.ok and state(qt_host, "line")["text"] == "שלום שלום"
