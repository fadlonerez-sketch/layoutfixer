"""Settings, stored as JSON in %APPDATA%\\LayoutFixer, ~/Library/Application Support/LayoutFixer on a Mac
(or $LAYOUTFIXER_DATA_DIR)."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "LayoutFixer"
IS_MAC = sys.platform == "darwin"
if IS_MAC:
    DEFAULT_HOTKEY = "Cmd+Fn"
    DEFAULT_FALLBACK_HOTKEY = ""  # on a Mac: an alternative that works at the same time (keyboards without Fn)
else:
    DEFAULT_HOTKEY = "Ctrl+Space"
    DEFAULT_FALLBACK_HOTKEY = "Ctrl+Shift+Space"


def data_dir() -> Path:
    override = os.environ.get("LAYOUTFIXER_DATA_DIR")
    if override:
        base = Path(override)
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Settings:
    enabled: bool = True
    hotkey: str = DEFAULT_HOTKEY
    fallback_hotkey: str = DEFAULT_FALLBACK_HOTKEY  # used automatically when the main one is taken
    to_hebrew_hotkey: str = ""                       # optional forced-direction shortcuts
    to_english_hotkey: str = ""
    switch_layout: bool = True
    notify_success: bool = True
    clipboard_fallback: bool = True                  # selection-only Ctrl+C/Ctrl+V for apps without accessibility
    max_whole_field_chars: int = 10_000
    start_at_login: bool = False                     # mirrored from the registry at start-up
    cooldown_ms: int = 400

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or data_dir() / "settings.json"
        s = cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM (Notepad)
        except FileNotFoundError:
            return s
        except (OSError, ValueError) as e:
            log.warning("settings unreadable (%s); using defaults", e)
            return s
        if not isinstance(raw, dict):
            return s
        for f in fields(cls):
            if f.name in raw:
                value = raw[f.name]
                default = getattr(s, f.name)
                if isinstance(default, bool):
                    if isinstance(value, bool):
                        setattr(s, f.name, value)
                elif isinstance(default, int):
                    if isinstance(value, int) and not isinstance(value, bool):
                        setattr(s, f.name, value)
                elif isinstance(value, type(default)):
                    setattr(s, f.name, value)
        s.max_whole_field_chars = min(max(s.max_whole_field_chars, 100), 1_000_000)
        s.cooldown_ms = min(max(s.cooldown_ms, 0), 5000)
        return s

    def save(self, path: Path | None = None) -> None:
        path = path or data_dir() / "settings.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
