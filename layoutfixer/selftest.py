"""`LayoutFixer.exe --selftest report.json`: checks a build works on this PC without changing anything.

No keystrokes, no clipboard, no focus changes. It converts sample text, compares the key table
with the installed layouts, starts UI Automation, registers/unregisters a rare test shortcut,
checks whether Ctrl+Space is free, and runs a native Edit control round trip inside its own
hidden window.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import sys
import traceback


def _checks() -> dict:
    from . import __version__
    from .converter import Direction, convert
    from .hotkeys import Hotkey, HotkeyThread
    from .keymap import KEYS
    from .uia import UiaClient
    from .win import api, layouts

    report: dict = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "checks": {}}
    c = report["checks"]

    c["convert_en_he"] = convert("akuo' nv eurv?", Direction.EN_TO_HE).text == "שלום, מה קורה?"
    c["convert_he_en"] = convert("יקךךם, 'םרךג.", Direction.HE_TO_EN).text == "hello' world/"

    installed = layouts.installed_layouts()
    c["hebrew_layout_installed"] = layouts.find_layout("he", installed) is not None
    c["english_layout_installed"] = layouts.find_layout("en", installed) is not None
    mismatches = []
    for hkl in installed:
        lang = layouts.lang_of(hkl)
        if lang == "he" or hkl & 0xFFFF == 0x0409:
            table = layouts.key_table(hkl)
            for sc, us, us_sh, he, he_sh in KEYS:
                want = (he, he_sh) if lang == "he" else (us, us_sh)
                if table.get(sc) != want:
                    mismatches.append(f"{hkl:#x}:{sc:#04x}")
    c["key_table_matches_windows"] = not mismatches
    if mismatches:
        report["mismatches"] = mismatches[:20]

    client = UiaClient()
    c["ui_automation"] = client.client is not None
    c["ui_automation_text"] = _uia_reads_own_edit(client)

    t = HotkeyThread(lambda name: None)
    try:
        reg = t.register("selftest", Hotkey.parse("Ctrl+Alt+Shift+F24"))
        c["hotkey_register"] = reg.ok
        t.unregister_all()
        space = t.register("probe", Hotkey.parse("Ctrl+Space"))
        report["ctrl_space_free"] = space.ok
        t.unregister_all()
    finally:
        t.stop()

    # Native Edit control round trip in our own hidden window (no other process is touched).
    from .targets.native_edit import NativeEditTarget
    parent = api.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, api.HWND_MESSAGE, None, None, None)
    edit = api.CreateWindowExW(0, "EDIT", None, 0x40000000, 0, 0, 100, 20, parent, None, None, None)
    try:
        buf = ctypes.create_unicode_buffer("akuo")
        api.SendMessageW(edit, api.WM_SETTEXT, 0, ctypes.addressof(buf))
        target = NativeEditTarget(edit, "Edit")
        state = target.read()
        target.replace(state, 0, 4, convert(state.text, Direction.EN_TO_HE).text)
        c["native_edit_round_trip"] = target.read().text == "שלום"
    finally:
        api.DestroyWindow(edit)
        api.DestroyWindow(parent)

    from PySide6.QtWidgets import QApplication
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])  # noqa: F841 - keep the application alive
    from .ui.icon import app_icon
    c["qt_ui"] = not app_icon().isNull()
    return report


def _uia_reads_own_edit(client) -> bool:
    """UI Automation finds the text pattern of an Edit control in a never-shown window of our own
    (catches a build whose bundled UI Automation wrappers are broken)."""
    import threading

    from .targets.uia_target import UiaTarget
    from .win import api

    ready = threading.Event()
    box: dict = {}

    def host() -> None:
        parent = api.CreateWindowExW(0, "STATIC", None, 0x80000000, -32000, -32000, 200, 50, None, None, None,
                                     None)
        edit = api.CreateWindowExW(0, "EDIT", None, 0x40000000, 0, 0, 200, 20, parent, None, None, None)
        buf = ctypes.create_unicode_buffer("akuo")
        api.SendMessageW(edit, api.WM_SETTEXT, 0, ctypes.addressof(buf))
        box.update(edit=edit, tid=ctypes.windll.kernel32.GetCurrentThreadId())
        ready.set()
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        api.DestroyWindow(edit)
        api.DestroyWindow(parent)

    t = threading.Thread(target=host, daemon=True)
    t.start()
    ready.wait(5)
    try:
        target = UiaTarget(client, client.element_from_handle(box["edit"]), paster=None)
        target.check_editable()
        return target.read().text == "akuo"
    except Exception:
        traceback.print_exc()
        return False
    finally:
        ctypes.windll.user32.PostThreadMessageW(box.get("tid", 0), 0x0012, 0, 0)  # WM_QUIT
        t.join(5)


def run_selftest(path: str) -> int:
    try:
        report = _checks()
        report["ok"] = all(report["checks"].values())
    except Exception:
        report = {"ok": False, "error": traceback.format_exc()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return 0 if report["ok"] else 1
