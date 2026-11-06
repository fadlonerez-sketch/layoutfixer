"""Runs ON A HIDDEN DESKTOP next to a real Chrome (see tests/test_chrome_real.py).

Drives Layout Fixer's real Engine + UiaTarget against real Chrome text fields through real UI
Automation: reading, building the text range, Select(), waiting for Chrome to report the
selection, and reading the result back. The Ctrl+V itself is SIMULATED (no keystrokes may be
sent): the fake paster checks that Chrome reports exactly the expected text as selected and
then writes what a paste would produce with ValuePattern.SetValue.

argv: result.json path. Writes {"cases": {name: {...}}, "log": [...]}.
"""

import ctypes
import json
import logging
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes as W
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

out_path = sys.argv[1]
result: dict = {"cases": {}, "log": []}


class ListHandler(logging.Handler):
    def emit(self, record):
        result["log"].append(record.getMessage())


logging.getLogger().addHandler(ListHandler())
logging.getLogger().setLevel(logging.INFO)

user32 = ctypes.WinDLL("user32")
ENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def chrome_window(title: str):
    found = []

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 256)
        if title in buf.value:
            found.append(h)
        return True

    user32.EnumWindows(ENUM(cb), 0)  # this desktop only
    return found[0] if found else None


class SimulatedPaste:
    """Stands in for ClipboardPaster: 'pastes' over whatever Chrome reports as selected."""

    def __init__(self, target, case):
        self.target = target
        self.case = case

    def paste(self, text, verify):
        from layoutfixer.paste import PasteResult
        t = self.target
        sel = t._selection()
        selected = sel.GetText(-1) if sel is not None else ""
        doc = t._doc_text()
        pre = t.tp.DocumentRange.Clone()
        pre.MoveEndpointByRange(1, sel, 0)
        start = len(pre.GetText(-1))
        self.case["selected_when_pasting"] = selected
        t.vp.SetValue(doc[:start] + text + doc[start + len(selected):])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if verify():
                return PasteResult(True, "")
            time.sleep(0.01)
        return PasteResult(False, "")


def run_case(c, root, name, aid, select=None, lang="he"):
    from layoutfixer.config import Settings
    from layoutfixer.engine import Engine
    from layoutfixer.targets.uia_target import UiaTarget
    from layoutfixer.win.focus import FocusInfo

    case = result["cases"].setdefault(name, {})
    el = None
    deadline = time.monotonic() + 20
    while el is None and time.monotonic() < deadline:
        el = root.FindFirst(4, c.client.CreatePropertyCondition(30011, aid)) or None
        if el is None:
            time.sleep(0.2)
    el.SetFocus()
    time.sleep(0.2)
    target = UiaTarget(c, el, None)
    if os.environ.get("LF_PROBE_SELECT_TIMEOUT"):  # e.g. "0" reproduces the old check-at-once behaviour
        target.select_timeout_s = float(os.environ["LF_PROBE_SELECT_TIMEOUT"])
    target.paster = SimulatedPaste(target, case)
    if select is not None:  # the user's selection, made the way a user would leave it
        rng = target._range_for(target._doc_text(), *select)
        rng.Select()
        case["user_selection_applied"] = target._wait_for_selection(target._doc_text()[select[0]:select[1]]) is not None

    class Env:
        class keyboard:
            @staticmethod
            def wait_for_release():
                return True

        def focus(self):
            return FocusInfo(1, 1, 1, 4242, "Chrome_WidgetWin_1", "chrome.exe", False)

        def is_blocked(self, f):
            return False

        def current_lang(self, f):
            return lang

        def switch_layout(self, f, lang):
            raise AssertionError("not used")

        def make_target(self, f, settings):
            return target

    mark = len(result["log"])
    out = Engine(Env(), lambda: Settings(switch_layout=False), own_pid=1).run()
    case.update(ok=out.ok, message=out.message, text_after=target._doc_text(),
                log=result["log"][mark:])


def main():
    from layoutfixer.uia import UiaClient
    deadline = time.monotonic() + 40
    hwnd = None
    while hwnd is None and time.monotonic() < deadline:
        hwnd = chrome_window("LFTEST")
        time.sleep(0.2)
    if hwnd is None:
        result["error"] = "Chrome window not found"
        return
    c = UiaClient()
    root = c.element_from_handle(hwnd)
    for args in [("input_whole_field", "inp"), ("textarea_selection", "ta", (6, 11)),
                 ("textarea_whole_field", "ta2"), ("contenteditable_whole_field", "ce")]:
        try:
            run_case(c, root, *args)
        except Exception:
            result["cases"].setdefault(args[0], {})["error"] = traceback.format_exc()


th = threading.Thread(target=lambda: _guard(main))


def _guard(fn):
    try:
        fn()
    except Exception:
        result["error"] = traceback.format_exc()


th.start()
th.join()
Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
