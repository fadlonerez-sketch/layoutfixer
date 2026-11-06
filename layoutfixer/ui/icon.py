"""The app icon, drawn in code (tray + window) and exported to assets/layoutfixer.ico at build time."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size: int, enabled: bool = True) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    r = QRectF(0.5, 0.5, size - 1, size - 1)
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.22, size * 0.22)
    p.fillPath(path, QColor("#2563eb") if enabled else QColor("#6b7280"))
    font = QFont("Segoe UI", 1)
    font.setBold(True)
    font.setPixelSize(max(7, int(size * 0.56)))
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    left = QRectF(0, -size * 0.02, size * 0.56, size)
    right = QRectF(size * 0.44, size * 0.02, size * 0.56, size)
    p.drawText(left, Qt.AlignmentFlag.AlignCenter, "א")  # א
    p.setPen(QColor("#dbeafe") if enabled else QColor("#e5e7eb"))
    p.drawText(right, Qt.AlignmentFlag.AlignCenter, "A")
    p.end()
    return img


def app_icon(enabled: bool = True) -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(QPixmap.fromImage(render(s, enabled)))
    return icon
