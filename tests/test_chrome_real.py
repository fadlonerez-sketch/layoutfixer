"""REAL CHROME on a hidden desktop: the UI Automation select-and-verify path that failed with
"Could not select the text safely; nothing was changed".

Chrome runs with a throw-away profile on a separate Windows desktop that is never displayed, so
it cannot take the user's focus or input and the user's own Chrome is not involved. Real: Chrome,
its accessibility tree, UI Automation reading, text ranges, Select() and the selection Chrome
reports, read-back verification. SIMULATED: the Ctrl+V keystroke and the clipboard (see
tests/hosts/chrome_uia_probe.py). The real shortcut press and real paste remain manual checks.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "hosts"))
from hidden_desktop import HiddenDesktop  # noqa: E402

CHROME = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe"

PAGE = """<!doctype html><meta charset=utf-8><title>LFTEST</title>
<input id=inp value="יקךךם">
<textarea id=ta>יקךךם 'םרךג</textarea>
<textarea id=ta2>akuo nv eurv? / יקךךם</textarea>
<div id=ce contenteditable role=textbox>יקךךם</div>"""

pytestmark = pytest.mark.skipif(not CHROME.exists() or os.environ.get("LAYOUTFIXER_SKIP_CHROME") == "1",
                                reason="Google Chrome not installed (or LAYOUTFIXER_SKIP_CHROME=1)")


@pytest.fixture(scope="module")
def chrome_results():
    with tempfile.TemporaryDirectory(prefix="lf-chrome-") as tmp:
        tmp = Path(tmp)
        page = tmp / "page.html"
        page.write_text(PAGE, encoding="utf-8")
        out = tmp / "result.json"
        desktop = HiddenDesktop(f"LayoutFixerTest{os.getpid()}{int(time.time())}")
        try:
            desktop.start(f'"{CHROME}" --user-data-dir="{tmp / "profile"}" --no-first-run --no-default-browser-check '
                          f'--disable-gpu --force-renderer-accessibility --disable-features=Translate '
                          f'--window-size=900,700 "{page.as_uri()}"')
            probe = desktop.start(f'"{sys.executable}" "{HERE / "hosts" / "chrome_uia_probe.py"}" "{out}"')
            code = probe.wait(120)
        finally:
            desktop.close()
            time.sleep(0.5)  # let Chrome release the profile folder
        assert code == 0, f"probe exit code {code}"
        data = json.loads(out.read_text(encoding="utf-8"))
    assert "error" not in data, data["error"]
    return data["cases"]


def _case(results, name):
    case = results[name]
    assert "error" not in case, case["error"]
    return case


def test_whole_input_field_selected_and_replaced(chrome_results):
    case = _case(chrome_results, "input_whole_field")
    assert case["ok"], case
    assert case["selected_when_pasting"] == "יקךךם"
    assert case["text_after"] == "hello"
    assert any("UIA select: 0-5 of 5 chars confirmed" in line for line in case["log"])


def test_selection_only_in_textarea(chrome_results):
    case = _case(chrome_results, "textarea_selection")
    assert case["user_selection_applied"]
    assert case["ok"], case
    assert case["selected_when_pasting"] == "'םרךג"
    assert case["text_after"] == "יקךךם world"


def test_whole_textarea_with_mixed_text_only_changed_span(chrome_results):
    case = _case(chrome_results, "textarea_whole_field")
    assert case["ok"], case
    # Hebrew layout active: Hebrew-layout characters change ("/" is typed by the Q key on Hebrew, so it
    # becomes "q"); Latin letters are not produced by the Hebrew layout and stay.
    assert case["text_after"] == "akuo nv eurv? q hello"


def test_contenteditable_editor_whole_field(chrome_results):
    case = _case(chrome_results, "contenteditable_whole_field")
    assert case["ok"], case
    assert case["selected_when_pasting"] == "יקךךם"
    assert case["text_after"] == "hello"
