"""A small notification in the corner that never takes the keyboard focus or mouse input."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

FONT = "font-size: 13px;" if sys.platform == "darwin" else "font: 10pt 'Segoe UI';"

STYLES = {
    "success": ("#14532d", "#bbf7d0"),
    "warning": ("#78350f", "#fde68a"),
    "error": ("#7f1d1d", "#fecaca"),
    "info": ("#1e3a8a", "#bfdbfe"),
}


class Toast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(380)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.last_message = ""
        self.last_level = ""

    def show_message(self, text: str, level: str = "info", duration_ms: int | None = None) -> None:
        bg, fg = STYLES.get(level, STYLES["info"])
        self.label.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: 8px; padding: 8px 14px;"
            f" {FONT} }}")
        self.label.setText(text)
        self.last_message, self.last_level = text, level
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 16)
        self.show()
        self._timer.start(duration_ms if duration_ms is not None else (1400 if level == "success" else 4500))
