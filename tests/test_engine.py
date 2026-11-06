"""The conversion flow and the dispatcher, with simulated Windows (fakes.py)."""

import threading
import time

import pytest

from fakes import FakeClipboard, FakeEnv, FakeKeyboard, FakeTarget, focus
from layoutfixer.config import Settings
from layoutfixer.converter import Direction
from layoutfixer.engine import ADMIN_MESSAGE, Dispatcher, Engine, Outcome
from layoutfixer.targets.base import TargetError, Unsupported
from layoutfixer.targets.clipboard_target import ClipboardSelectionTarget

ORIGINAL = {13: "precious\0".encode("utf-16-le"), 15: b"file-list"}


def engine(env, **s):
    return Engine(env, lambda: Settings(**s), own_pid=1)


def test_whole_field_success_switches_layout():
    t = FakeTarget("akuo' nv eurv?")
    env = FakeEnv(target=t)
    out = engine(env).run()
    assert out.ok and out.level == "success" and out.direction is Direction.EN_TO_HE
    assert t.text == "שלום, מה קורה?"
    assert env.switched == ["he"]
    assert t.closed


def test_reverse_and_switch_to_english():
    t = FakeTarget("יקךךם")
    env = FakeEnv(target=t, lang="he")
    out = engine(env).run()
    assert out.ok and t.text == "hello" and env.switched == ["en"]
    assert out.message == "Converted to English"


def test_selection_only_rest_untouched():
    t = FakeTarget("Dear team, akuo nv eurv - thanks", sel=(11, 23))
    assert engine(FakeEnv(target=t)).run().ok
    assert t.text == "Dear team, שלום מה קורה - thanks"
    assert t.replaced == [(11, 23, "שלום מה קורה")]


def test_only_changed_span_is_replaced():
    t = FakeTarget("שלום לכולם akuo")
    assert engine(FakeEnv(target=t, lang="en")).run().ok
    assert t.replaced == [(11, 15, "שלום")]


def test_empty_field():
    t = FakeTarget("   ")
    out = engine(FakeEnv(target=t)).run()
    assert not out.ok and "empty" in out.message and t.replaced == []


def test_nothing_to_convert():
    t = FakeTarget("12345 !!")
    out = engine(FakeEnv(target=t)).run()
    assert not out.ok and "Nothing to convert" in out.message


def test_unknown_layout_changes_nothing():
    t = FakeTarget("akuo")
    out = engine(FakeEnv(target=t, lang=None)).run()
    assert not out.ok and "neither English nor Hebrew" in out.message and t.replaced == []


def test_direction_follows_the_layout_not_the_text():
    t = FakeTarget("שלום akuo")
    out = engine(FakeEnv(target=t, lang="he")).run()  # Hebrew layout: Hebrew-layout characters -> English
    assert out.ok and t.text == "akuo akuo" and out.direction is Direction.HE_TO_EN
    t = FakeTarget("akuo")
    out = engine(FakeEnv(target=t, lang="he")).run()
    assert not out.ok and "Nothing to convert" in out.message and t.replaced == []


def test_forced_direction():
    t = FakeTarget("שלום akuo")
    out = engine(FakeEnv(target=t, lang="he")).run(force=Direction.EN_TO_HE)
    assert out.ok and t.text == "שלום שלום"


def test_too_long_without_selection():
    t = FakeTarget("akuo " * 50)
    out = engine(FakeEnv(target=t), max_whole_field_chars=100).run()
    assert not out.ok and t.replaced == []


def test_long_field_with_selection_is_fine():
    t = FakeTarget("x" * 500 + "akuo", sel=(500, 504))
    out = engine(FakeEnv(target=t), max_whole_field_chars=100).run()
    assert out.ok and t.text.endswith("שלום")


def test_layout_switch_failure_is_reported_not_hidden():
    t = FakeTarget("akuo")
    out = engine(FakeEnv(target=t, switch_ok=False)).run()
    assert out.ok and out.level == "warning" and "NOT switched" in out.message


def test_switch_disabled():
    env = FakeEnv(target=FakeTarget("akuo"))
    assert engine(env, switch_layout=False).run().ok
    assert env.switched == []


def test_admin_window_refused():
    out = engine(FakeEnv(target=FakeTarget("akuo"), blocked=True)).run()
    assert not out.ok and out.message == ADMIN_MESSAGE


def test_modifiers_still_held_changes_nothing():
    t = FakeTarget("akuo")
    out = engine(FakeEnv(target=t, keyboard=FakeKeyboard(released=False))).run()
    assert not out.ok and "Release" in out.message and t.text == "akuo"


def test_no_focus():
    out = engine(FakeEnv(focus_info=None)).run()
    assert not out.ok


def test_own_window_is_silent():
    out = engine(FakeEnv(focus_info=focus(pid=1), target=FakeTarget("akuo"))).run()
    assert out.level == "silent"


def test_unsupported_app_message():
    out = engine(FakeEnv(make_error=Unsupported("cannot read"))).run()
    assert not out.ok and out.message == "cannot read"


def test_replace_error_reported_and_target_closed():
    t = FakeTarget("akuo", fail_replace=TargetError("refused"))
    out = engine(FakeEnv(target=t)).run()
    assert not out.ok and out.message == "refused" and t.closed and t.text == "akuo"


def test_unexpected_exception_is_caught():
    t = FakeTarget("akuo", fail_replace=RuntimeError("boom"))
    out = engine(FakeEnv(target=t)).run()
    assert not out.ok and "Unexpected" in out.message and t.closed


# ------------------------------------------------- clipboard selection fallback (simulated input + clipboard)
def clip_rig(selected: str | None, paste_ok=True):
    clip = FakeClipboard(ORIGINAL)
    keys = FakeKeyboard()
    field = {"text": f"before {selected} after" if selected else "before after", "pasted": None}
    if selected:
        keys.on_copy = lambda: clip.external_copy(selected)
    if paste_ok:
        def paste():
            field["pasted"] = clip.get_text()
        keys.on_paste = paste
    target = ClipboardSelectionTarget(clip, keys, copy_timeout_s=0.1, paste_delay_s=0, sleep=lambda s: None)
    return clip, keys, field, target


def test_clipboard_fallback_converts_selection_and_restores_clipboard():
    clip, keys, field, target = clip_rig("akuo")
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert out.ok and out.level == "warning"  # pasted, but this kind of app can't be read back
    assert field["pasted"] == "שלום"
    assert keys.events == ["ctrl+c", "ctrl+v"]
    assert clip.formats == ORIGINAL


def test_clipboard_fallback_without_selection_stops_and_restores():
    clip, keys, field, target = clip_rig(None)
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert not out.ok and "select the text first" in out.message
    assert keys.events == ["ctrl+c"]  # never pastes
    assert clip.formats == ORIGINAL


def test_clipboard_fallback_ignores_whole_line_copy():
    clip, keys, field, target = clip_rig("akuo nv\n")
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert not out.ok and "ctrl+v" not in keys.events and clip.formats == ORIGINAL


def test_clipboard_fallback_paste_rejected_restores():
    clip, keys, field, target = clip_rig("akuo")
    keys.accept = False
    keys.on_copy = lambda: clip.external_copy("akuo")
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert not out.ok
    assert clip.formats == ORIGINAL


def test_clipboard_restored_when_conversion_crashes(monkeypatch):
    clip, keys, field, target = clip_rig("akuo")
    import layoutfixer.engine as eng_mod
    monkeypatch.setattr(eng_mod, "convert", lambda *a: (_ for _ in ()).throw(RuntimeError("bug")))
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert not out.ok and clip.formats == ORIGINAL


# ------------------------------------------------- dispatcher: rapid presses
def test_rapid_presses_convert_once():
    calls = []
    started = threading.Event()
    release = threading.Event()

    def slow_run(force):
        calls.append(force)
        started.set()
        release.wait(2)
        return Outcome(True, "ok", "success")

    outcomes = []
    d = Dispatcher(slow_run, outcomes.append, cooldown_s=0.3)
    try:
        assert d.trigger()
        started.wait(2)
        assert [d.trigger() for _ in range(10)] == [False] * 10
        release.set()
        deadline = time.monotonic() + 2
        while not outcomes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not d.trigger()  # still inside the cooldown
        assert len(calls) == 1 and len(outcomes) == 1 and d.dropped == 11
        time.sleep(0.35)
        assert d.trigger()  # a deliberate press later works again (converts back)
        deadline = time.monotonic() + 2
        while len(outcomes) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(calls) == 2
    finally:
        d.stop()


def test_double_press_does_not_convert_back():
    t = FakeTarget("akuo")
    env = FakeEnv(target=t)
    eng = engine(env)
    outcomes = []
    d = Dispatcher(eng.run, outcomes.append, cooldown_s=0.5)
    try:
        d.trigger()
        deadline = time.monotonic() + 2
        while not outcomes and time.monotonic() < deadline:
            time.sleep(0.005)
        d.trigger()  # second press right after: dropped
        time.sleep(0.1)
        assert t.text == "שלום" and len(outcomes) == 1
    finally:
        d.stop()


def test_dispatcher_survives_engine_crash():
    outcomes = []

    def crash(force):
        raise RuntimeError("x")

    d = Dispatcher(crash, outcomes.append, cooldown_s=0)
    try:
        d.trigger()
        deadline = time.monotonic() + 2
        while not outcomes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert outcomes and not outcomes[0].ok
        assert not d.busy
    finally:
        d.stop()


def test_changed_segments_split_around_objects():
    from layoutfixer.engine import changed_segments
    old = "akuo ￼ nv"
    new = "שלום ￼ מה"
    assert changed_segments(old, new) == [(0, 4), (7, 9)]
    assert changed_segments("abc", "abc") == []
    assert changed_segments("ab cd", "aX cY") == [(1, 5)]


def test_engine_replaces_each_segment_separately():
    t = FakeTarget("akuo ￼ nv")
    out = engine(FakeEnv(target=t)).run()
    assert out.ok and t.text == "שלום ￼ מה"
    assert t.replaced == [(7, 9, "מה"), (0, 4, "שלום")]


def test_selection_only_target_with_object_refused():
    clip, keys, field, target = clip_rig("akuo ￼ nv")
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert not out.ok and "picture" in out.message and "ctrl+v" not in keys.events
    assert clip.formats == ORIGINAL


def test_failure_after_first_segment_reports_partial_change():
    class Flaky(FakeTarget):
        def replace(self, state, start, end, new_text):
            if self.replaced:
                raise TargetError("boom")
            return super().replace(state, start, end, new_text)

    t = Flaky("akuo ￼ nv")
    out = engine(FakeEnv(target=t)).run()
    assert not out.ok and out.level == "warning" and "Ctrl+Z" in out.message


def test_clipboard_fallback_late_copy_is_still_restored():
    """The app answers our Ctrl+C only after the copy timeout: its copy must not replace the clipboard."""
    clip = FakeClipboard(ORIGINAL)
    keys = FakeKeyboard()
    target = ClipboardSelectionTarget(clip, keys, copy_timeout_s=0.01, paste_delay_s=0,
                                      late_copy_grace_s=0, sleep=lambda s: None)
    real_close = target.close

    def close_after_late_copy():
        clip.external_copy("late copy")  # arrives after we gave up
        real_close()

    target.close = close_after_late_copy
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert not out.ok and clip.formats == ORIGINAL


def test_clipboard_fallback_hung_app_reports_clipboard_kept():
    clip, keys, field, target = clip_rig("akuo")
    target.wait_idle = lambda: False
    out = engine(FakeEnv(target=target, keyboard=keys)).run()
    assert out.ok and out.level == "warning" and "not responding" in out.message
    assert clip.get_text() == "שלום"


# ------------------------------------------------- finding the field (SIMULATED UI Automation)
class _El:
    def __init__(self, control_type, text=None):
        self.CurrentControlType = control_type
        self.CurrentClassName = "x"
        self.CurrentIsPassword = False
        self.CurrentIsEnabled = True
        self.text = text


class _Range:
    def GetAttributeValue(self, attr):
        return False


class _TextPattern:
    DocumentRange = _Range()


class _Client:
    """Like Chrome/Electron: the first answers are the bare window pane, then the real text field."""

    def __init__(self, panes_first):
        self.answers = [_El(50033)] * panes_first + [_El(50004, "akuo")]
        self.asked = 0

    def focused_element(self):
        self.asked += 1
        return self.answers[min(self.asked, len(self.answers)) - 1]

    def text_pattern(self, el):
        return _TextPattern() if el.text is not None else None

    def value_pattern(self, el):
        return None


def _env_with(client, monkeypatch):
    from layoutfixer import win_env
    env = win_env.WindowsEnvironment()
    env._uia = client
    f = focus()
    monkeypatch.setattr(win_env.wfocus, "get_focus", lambda: f)
    monkeypatch.setattr(win_env, "UIA_RETRY_S", 0.001)
    return env, f


def test_field_found_after_chromium_builds_its_accessibility_tree(monkeypatch):
    client = _Client(panes_first=3)
    env, f = _env_with(client, monkeypatch)
    target = env.make_target(f, Settings(clipboard_fallback=False))
    assert target.kind == "uia" and client.asked == 4


def test_no_text_field_gives_up_after_the_settle_time(monkeypatch):
    from layoutfixer import win_env
    client = _Client(panes_first=10_000)
    env, f = _env_with(client, monkeypatch)
    monkeypatch.setattr(win_env, "UIA_SETTLE_S", 0.05)
    with pytest.raises(Unsupported):
        env.make_target(f, Settings(clipboard_fallback=False))
    assert client.asked > 1


def test_focus_moving_elsewhere_stops_the_retries(monkeypatch):
    from layoutfixer import win_env
    client = _Client(panes_first=10_000)
    env, f = _env_with(client, monkeypatch)
    monkeypatch.setattr(win_env.wfocus, "get_focus", lambda: focus(pid=999))
    with pytest.raises(Unsupported):
        env.make_target(f, Settings(clipboard_fallback=False))
    assert client.asked == 1


# ------------------------------------------------- diagnostic log
def test_log_names_each_step_but_never_the_text(caplog):
    caplog.set_level("INFO")
    t = FakeTarget("akuo secret")
    assert engine(FakeEnv(target=t)).run().ok
    log = caplog.text
    for step in ("focus:", "layout: active=en", "target: fake", "read: 11 chars", "convert:", "replace:",
                 "switch layout: ok=True"):
        assert step in log
    assert "akuo" not in log and "secret" not in log and "שלום" not in log


def test_log_says_which_step_failed(caplog):
    caplog.set_level("INFO")
    engine(FakeEnv(make_error=Unsupported("cannot read"))).run()
    assert "FAILED at find text field: cannot read" in caplog.text
    caplog.clear()
    engine(FakeEnv(target=FakeTarget("akuo"), lang=None)).run()
    assert "FAILED at layout" in caplog.text
