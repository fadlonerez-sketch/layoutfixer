"""Settings window."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from ..config import DEFAULT_FALLBACK_HOTKEY, DEFAULT_HOTKEY, Settings
from ..hotkeys import (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, VK_TO_NAME, Hotkey, HotkeyError,
                       HotkeyStatus)
from .icon import app_icon

_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


class HotkeyEdit(QLineEdit):
    """Click, then press the new shortcut. Backspace clears it (when ``allow_empty``)."""

    recording = Signal(bool)

    def __init__(self, text: str = "", allow_empty: bool = False, parent=None):
        super().__init__(text, parent)
        self.allow_empty = allow_empty
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # record only after a click, not on window open
        self.setPlaceholderText("Not set - click and press keys" if allow_empty else "Click and press keys")
        self.error = ""

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self.recording.emit(True)

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self.recording.emit(False)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        vk = e.nativeVirtualKey()
        mods = 0
        qm = e.modifiers()
        if qm & Qt.KeyboardModifier.ControlModifier:
            mods |= MOD_CONTROL
        if qm & Qt.KeyboardModifier.AltModifier:
            mods |= MOD_ALT
        if qm & Qt.KeyboardModifier.ShiftModifier:
            mods |= MOD_SHIFT
        if qm & Qt.KeyboardModifier.MetaModifier:
            mods |= MOD_WIN
        if vk in _MODIFIER_VKS:
            return
        if not mods and vk == 0x1B:  # Escape: stop recording
            self.clearFocus()
            return
        if not mods and vk in (0x08, 0x2E) and self.allow_empty:
            self.setText("")
            self.error = ""
            return
        if vk not in VK_TO_NAME:
            self.error = "That key can't be used in a shortcut"
            self.setToolTip(self.error)
            return
        hk = Hotkey(mods, vk)
        try:
            hk.validate()
        except HotkeyError as err:
            self.error = str(err)
            self.setToolTip(self.error)
            return
        self.error = ""
        self.setToolTip("")
        self.setText(str(hk))


class SettingsWindow(QWidget):
    saved = Signal(object)          # Settings
    recording = Signal(bool)        # a shortcut field is recording keys

    def __init__(self, settings: Settings, status: HotkeyStatus, layouts_info: Callable[[], str], mac=None):
        """``mac``: a mac.ui.MacSupport on macOS (shortcut recording, permission and Fn key hints)."""
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Layout Fixer - Settings")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(520)
        self._layouts_info = layouts_info
        self._settings = settings
        self.mac = mac

        if mac is not None:
            from ..mac.hotkeys import MacHotkey
            from ..mac.ui import MacHotkeyEdit
            self._parse = MacHotkey.parse
            edit = lambda text, allow_empty=False: MacHotkeyEdit(text, mac.recorder, allow_empty)  # noqa: E731
        else:
            self._parse = Hotkey.parse
            edit = HotkeyEdit
        self.enabled = QCheckBox("Enabled (the shortcut fixes the focused text field)")
        self.hotkey = edit(settings.hotkey)
        self.fallback = edit(settings.fallback_hotkey, allow_empty=True)
        self.to_he = edit(settings.to_hebrew_hotkey, allow_empty=True)
        self.to_en = edit(settings.to_english_hotkey, allow_empty=True)
        for w in (self.hotkey, self.fallback, self.to_he, self.to_en):
            w.recording.connect(self.recording)
        reset = QPushButton("Reset")
        reset.clicked.connect(lambda: (self.hotkey.setText(DEFAULT_HOTKEY),
                                       self.fallback.setText(DEFAULT_FALLBACK_HOTKEY)))
        row = QHBoxLayout()
        row.addWidget(self.hotkey, 1)
        row.addWidget(reset)
        self.status = QLabel()
        self.status.setWordWrap(True)

        keys = QFormLayout()
        keys.addRow("Fix text:", row)
        keys.addRow("Also use (keyboards without Fn):" if mac is not None else "If that is taken, use:", self.fallback)
        keys.addRow("Always to Hebrew:", self.to_he)
        keys.addRow("Always to English:", self.to_en)
        keys.addRow("", self.status)
        keys_box = QGroupBox("Shortcuts")
        keys_box.setLayout(keys)

        self.switch_layout = QCheckBox("Switch the keyboard language after converting")
        self.notify = QCheckBox("Show a short notification after each conversion")
        self.fallback_clip = QCheckBox("In apps that hide their text from accessibility tools, convert the "
                                       "selection with copy/paste (clipboard is restored)")
        self.max_chars = QSpinBox()
        self.max_chars.setRange(100, 1_000_000)
        self.max_chars.setSingleStep(1000)
        self.max_chars.setSuffix(" characters")
        self.startup = QCheckBox("Start Layout Fixer when I log in" if mac is not None
                                 else "Start Layout Fixer when I sign in to Windows")
        behaviour = QFormLayout()
        behaviour.addRow(self.enabled)
        behaviour.addRow(self.switch_layout)
        behaviour.addRow(self.notify)
        behaviour.addRow(self.fallback_clip)
        behaviour.addRow("Whole-field limit:", self.max_chars)
        behaviour.addRow(self.startup)
        beh_box = QGroupBox("Behaviour")
        beh_box.setLayout(behaviour)

        self.layouts = QLabel()
        self.layouts.setWordWrap(True)
        self.layouts.setTextFormat(Qt.TextFormat.RichText)  # "&nbsp;" alone is not auto-detected as rich text
        self.message = QLabel()
        self.message.setWordWrap(True)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.message, 1)
        buttons.addWidget(save)
        buttons.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addWidget(keys_box)
        lay.addWidget(beh_box)
        if mac is not None:
            lay.addWidget(self._mac_box(mac))
        lay.addWidget(self.layouts)
        lay.addLayout(buttons)
        self.load(settings, status)

    def load(self, settings: Settings, status: HotkeyStatus) -> None:
        self._settings = settings
        self.enabled.setChecked(settings.enabled)
        self.hotkey.setText(settings.hotkey)
        self.fallback.setText(settings.fallback_hotkey)
        self.to_he.setText(settings.to_hebrew_hotkey)
        self.to_en.setText(settings.to_english_hotkey)
        self.switch_layout.setChecked(settings.switch_layout)
        self.notify.setChecked(settings.notify_success)
        self.fallback_clip.setChecked(settings.clipboard_fallback)
        self.max_chars.setValue(settings.max_whole_field_chars)
        self.startup.setChecked(settings.start_at_login)
        self.show_status(status)
        self.layouts.setText(self._layouts_info())
        if self.mac is not None:
            self._refresh_mac()

    def _mac_box(self, mac) -> QGroupBox:
        self.permission = QLabel()
        self.permission.setWordWrap(True)
        open_ax = QPushButton("Open Accessibility Settings")
        open_ax.clicked.connect(mac.open_accessibility)
        row = QHBoxLayout()
        row.addWidget(self.permission, 1)
        row.addWidget(open_ax)
        self.fn_note = QLabel()
        self.fn_note.setWordWrap(True)
        open_kb = QPushButton("Open Keyboard Settings")
        open_kb.clicked.connect(mac.open_keyboard)
        row2 = QHBoxLayout()
        row2.addWidget(self.fn_note, 1)
        row2.addWidget(open_kb)
        box = QGroupBox("macOS")
        v = QVBoxLayout(box)
        v.addLayout(row)
        v.addLayout(row2)
        return box

    def _refresh_mac(self) -> None:
        if self.mac.trusted():
            self.permission.setText("<span style='color:#15803d'>Accessibility permission: on</span>")
        else:
            self.permission.setText("<span style='color:#b91c1c'>Accessibility permission: <b>off</b></span> - "
                                    "turn on Layout Fixer in Privacy &amp; Security &gt; Accessibility. "
                                    "The shortcut starts working a few seconds later.")
        action = self.mac.fn_key_action()
        text = ("Fn on its own: macOS is set to <b>{}</b>. ".format(action) if action else "")
        if action != "Do Nothing":
            text += ("If pressing Cmd+Fn also triggers that (emoji picker, input source, dictation), set "
                     "Keyboard &gt; “Press 🌐 key to” &gt; Do Nothing.")
        self.fn_note.setText(text)

    def show_status(self, status: HotkeyStatus) -> None:
        ok = status.active or not status.enabled
        color = "#15803d" if ok and not status.errors else ("#b45309" if status.active else "#b91c1c")
        text = status.summary()
        if status.active and status.errors:
            text += "<br>" + "<br>".join(status.errors)
        self.status.setText(f"<span style='color:{color}'>{text}</span>")

    def _save(self) -> None:
        for edit in (self.hotkey, self.fallback, self.to_he, self.to_en):
            if edit.text():
                try:
                    self._parse(edit.text())
                except HotkeyError as e:
                    self.message.setText(f"<span style='color:#b91c1c'>{e}</span>")
                    return
        if not self.hotkey.text():
            self.message.setText("<span style='color:#b91c1c'>Choose a shortcut</span>")
            return
        new = replace(self._settings, enabled=self.enabled.isChecked(), hotkey=self.hotkey.text(),
                      fallback_hotkey=self.fallback.text(), to_hebrew_hotkey=self.to_he.text(),
                      to_english_hotkey=self.to_en.text(), switch_layout=self.switch_layout.isChecked(),
                      notify_success=self.notify.isChecked(), clipboard_fallback=self.fallback_clip.isChecked(),
                      max_whole_field_chars=self.max_chars.value(), start_at_login=self.startup.isChecked())
        self.message.setText("Saved")
        self.saved.emit(new)
