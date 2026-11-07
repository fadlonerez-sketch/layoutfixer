"""Render README screenshots of the real Settings window off-screen (no window is shown).

    set QT_QPA_PLATFORM=offscreen
    .venv\\Scripts\\python tools\\render_screenshots.py [out_dir]

The window is built from default Settings with a demo shortcut status ("Ctrl+Space" active) and a fixed
keyboard-layouts line, then captured with QWidget.grab(). Nothing is registered, read from or written to
the system: no hotkeys, no keyboard layouts, no clipboard, no registry.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LAYOUTFIXER_DATA_DIR", tempfile.mkdtemp(prefix="lf-render-"))
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and "QT_QPA_FONTDIR" not in os.environ:
    windir = os.environ.get("WINDIR", "")
    if windir:  # the offscreen platform reads fonts from a folder
        os.environ["QT_QPA_FONTDIR"] = str(Path(windir) / "Fonts")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from layoutfixer.config import Settings  # noqa: E402
from layoutfixer.hotkeys import Hotkey, HotkeyStatus, Registration  # noqa: E402
from layoutfixer.ui.settings_window import SettingsWindow  # noqa: E402

DEMO_LAYOUTS = "Hebrew keyboard: installed &nbsp;·&nbsp; English keyboard: installed"


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("fusion")            # the native Windows style needs the windows platform
    app.setFont(QFont("Segoe UI", 9))  # the Windows UI font (the offscreen platform has no default)
    settings = Settings()
    status = HotkeyStatus(True, convert=Registration(True, Hotkey.parse(settings.hotkey)))
    w = SettingsWindow(settings, status, lambda: DEMO_LAYOUTS)
    w.resize(w.sizeHint().expandedTo(w.minimumSize()))
    w.ensurePolished()
    path = out / "settings.png"
    if not w.grab().save(str(path), "PNG"):
        print(f"could not write {path}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
