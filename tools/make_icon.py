"""Write assets/layoutfixer.ico from the icon drawn in layoutfixer/ui/icon.py."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "windows"  # real fonts (offscreen has none); no window is shown

from PySide6.QtGui import QGuiApplication  # noqa: E402

from layoutfixer.ui.icon import render  # noqa: E402


def main() -> int:
    app = QGuiApplication([])  # noqa: F841
    out = ROOT / "assets" / "layoutfixer.ico"
    out.parent.mkdir(exist_ok=True)
    # Qt's ICO writer stores one image per file; build a multi-size ICO by hand (PNG entries).
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        render(size).save(buf, "PNG")
        images.append((size, bytes(ba.data())))
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + len(images).to_bytes(2, "little")
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        entries += len(png).to_bytes(4, "little") + offset.to_bytes(4, "little")
        offset += len(png)
        blobs += png
    out.write_bytes(header + entries + blobs)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
