"""`Layout Fixer.app/Contents/MacOS/LayoutFixer --selftest report.json`: checks the Mac build on that Mac.

Changes nothing: no keystrokes, no clipboard writes, no input-source switch, no
event tap. It converts sample text, reads the installed Mac layouts with
UCKeyTranslate and compares them with the built-in table, loads the
Accessibility, Quartz and AppKit bindings, and reports the Accessibility
permission and the Fn/Globe key setting.
"""

from __future__ import annotations

import json
import os
import sys
import traceback


def _checks() -> dict:
    from .. import __version__
    from ..converter import Direction, convert
    from . import permissions, tis
    from .keymap_mac import BUILTIN_EN_TO_HE, BUILTIN_HE_TO_EN, BUILTIN_ROWS, build_tables
    from .layouts import pick_layout, rows_for

    report: dict = {"version": __version__, "platform": sys.platform, "python": sys.version.split()[0],
                    "checks": {}, "info": {}}
    c, info = report["checks"], report["info"]
    builtin = (BUILTIN_EN_TO_HE, BUILTIN_HE_TO_EN)
    c["convert_en_he"] = convert("akuo' nv eurv?", Direction.EN_TO_HE, builtin).text == "שלום, מה קורה?"
    c["convert_he_en"] = convert("יקךךם", Direction.HE_TO_EN, builtin).text == "hello"

    enabled, installed = tis.list_sources(False), tis.list_sources(True)
    info["input_menu"] = [f"{s.id} ({s.lang or '-'})" for s in enabled]
    current = tis.current_source()
    info["current_input_source"] = current.id if current else None
    c["input_sources_listed"] = bool(installed)
    he, en = pick_layout(installed, "he"), pick_layout(installed, "en")
    c["hebrew_layout_on_this_mac"] = he is not None
    c["english_layout_on_this_mac"] = en is not None
    info["hebrew_in_input_menu"] = pick_layout(enabled, "he") is not None
    info["english_in_input_menu"] = pick_layout(enabled, "en") is not None
    if he and en:
        kbd = tis.keyboard_type()
        info["keyboard_type"] = kbd
        read_en = tis.KeyTranslator(tis.layout_data(en.id), kbd).char
        read_he = tis.KeyTranslator(tis.layout_data(he.id), kbd).char
        rows = rows_for("en", read_en, read_he)
        en_he, he_en = build_tables(rows)
        c["layouts_read_with_uckeytranslate"] = en_he.get("a") == "ש" and he_en.get("ש") == "a"
        c["convert_with_this_macs_layouts"] = convert("akuo", Direction.EN_TO_HE, (en_he, he_en)).text == "שלום"
        by_code = {r[0]: r for r in BUILTIN_ROWS}
        info["differences_from_builtin_table"] = [
            {"key": r[0], "this_mac": list(r[1:]), "builtin": list(by_code[r[0]][1:])}
            for r in rows if r[0] in by_code and tuple(r[1:]) != tuple(by_code[r[0]][1:])]

    from .ax import AXClient
    AXClient()
    c["accessibility_api_loads"] = True
    info["accessibility_permission"] = permissions.is_trusted()
    info["fn_key_action"] = permissions.fn_key_action()
    info["secure_input_on"] = tis.secure_input()

    import Quartz
    from .keyboard import held_modifiers
    held_modifiers()
    c["quartz_loads"] = Quartz.CGEventTapCreate is not None

    from .clipboard import MacClipboard
    c["pasteboard_readable"] = MacClipboard().sequence() >= 0

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from ..ui.icon import app_icon
    c["qt_ui"] = not app_icon().isNull()
    return report


def run_selftest(path: str) -> int:
    try:
        report = _checks()
        report["ok"] = all(report["checks"].values())
    except Exception:
        report = {"ok": False, "error": traceback.format_exc()}
    with open(os.path.expanduser(path), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return 0 if report["ok"] else 1
