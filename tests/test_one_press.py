"""Regression: ONE Ctrl+Space press must convert the text AND switch the layout (SIMULATED field).

The bug (log of 2026-10-28): in Chrome, with only a caret in the field, the first press asked UI
Automation to select the text and checked the selection immediately. Chrome applies Select()
asynchronously, so the check saw the old caret and the press failed before replacing anything or
switching the layout. Chrome then applied the selection, so the SECOND press found the text already
selected and succeeded - "it needs two presses".

The field below behaves like Chrome: Select() takes effect only some milliseconds later, and a
paste replaces whatever the field reports as selected at that moment. The real Chrome behaviour
is covered in test_chrome_real.py.
"""

import time

from fakes import FakeEnv
from layoutfixer.config import Settings
from layoutfixer.engine import Dispatcher, Engine
from layoutfixer.paste import PasteResult
from layoutfixer.targets.uia_target import UiaTarget


class AsyncField:
    def __init__(self, text: str, delay_s: float = 0.02):
        self.text = text
        self.sel = (len(text), len(text))  # just a caret at the end, nothing selected
        self.delay_s = delay_s
        self.pending = None
        self.selects = 0

    def selection(self):
        if self.pending and time.monotonic() >= self.pending[1]:
            self.sel, self.pending = self.pending[0], None
        return self.sel


class Range:
    def __init__(self, field, a, b):
        self.f, self.a, self.b = field, a, b

    def Clone(self):
        return Range(self.f, self.a, self.b)

    def MoveEndpointByRange(self, endpoint, other, other_endpoint):
        pos = other.a if other_endpoint == 0 else other.b
        if endpoint == 0:
            self.a, self.b = pos, max(pos, self.b)
        else:
            self.a, self.b = min(self.a, pos), pos

    def MoveEndpointByUnit(self, endpoint, unit, n):
        if endpoint == 0:
            self.a = max(0, min(len(self.f.text), self.a + n))
            self.b = max(self.a, self.b)
        else:
            self.b = max(0, min(len(self.f.text), self.b + n))
            self.a = min(self.a, self.b)
        return n

    def GetText(self, n):
        return self.f.text[self.a:self.b]

    def GetAttributeValue(self, attr):
        return False

    def Select(self):  # asynchronous, like Chromium
        self.f.selects += 1
        self.f.pending = ((self.a, self.b), time.monotonic() + self.f.delay_s)


class Selections:
    def __init__(self, rng):
        self.Length = 1
        self.rng = rng

    def GetElement(self, i):
        return self.rng


class TextPattern:
    def __init__(self, field):
        self.f = field

    @property
    def DocumentRange(self):
        return Range(self.f, 0, len(self.f.text))

    def GetSelection(self):
        return Selections(Range(self.f, *self.f.selection()))


class Element:
    CurrentIsPassword = False
    CurrentIsEnabled = True
    CurrentControlType = 50004  # Edit, as Chrome reports its text fields


class Client:
    def __init__(self, field):
        self.f = field

    def text_pattern(self, el):
        return TextPattern(self.f)

    def value_pattern(self, el):
        return None


class Paste:
    """Ctrl+V: replaces what the field reports as selected right now (the caret if nothing is)."""

    def __init__(self, field):
        self.f = field

    def paste(self, text, verify):
        a, b = self.f.selection()
        self.f.text = self.f.text[:a] + text + self.f.text[b:]
        self.f.sel = (a + len(text), a + len(text))
        return PasteResult(verify(), "")


def chrome_like(text, lang, **kw):
    field = AsyncField(text)
    target = UiaTarget(Client(field), Element(), Paste(field), **kw)
    return field, FakeEnv(target=target, lang=lang)


def test_one_press_converts_and_switches_once_hebrew_to_english():
    field, env = chrome_like("יקךךם", "he")
    out = Engine(env, lambda: Settings(), own_pid=1).run()
    assert out.ok and out.level == "success", out
    assert field.text == "hello"
    assert env.switched == ["en"]  # exactly one switch, in the same press
    assert field.selects == 1


def test_one_press_converts_and_switches_once_english_to_hebrew():
    field, env = chrome_like("akuo", "en")
    out = Engine(env, lambda: Settings(), own_pid=1).run()
    assert out.ok and field.text == "שלום" and env.switched == ["he"]


def test_the_old_immediate_check_is_what_needed_a_second_press():
    """Checking the selection at once (no wait) fails on the first press, exactly as in the log."""
    field, env = chrome_like("יקךךם", "he", select_timeout_s=0)
    out = Engine(env, lambda: Settings(), own_pid=1).run()
    assert not out.ok and field.text == "יקךךם" and env.switched == []
    time.sleep(0.03)  # Chrome applies the selection after the press has given up...
    out = Engine(env, lambda: Settings(), own_pid=1).run()
    assert out.ok and field.text == "hello"  # ...so the second press worked


def test_single_hotkey_event_through_the_dispatcher():
    field, env = chrome_like("יקךךם", "he")
    outcomes = []
    d = Dispatcher(Engine(env, lambda: Settings(), own_pid=1).run, outcomes.append, cooldown_s=0.4)
    try:
        assert d.trigger()  # one WM_HOTKEY
        deadline = time.monotonic() + 3
        while not outcomes and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(outcomes) == 1 and outcomes[0].ok
        assert field.text == "hello" and env.switched == ["en"]
    finally:
        d.stop()
