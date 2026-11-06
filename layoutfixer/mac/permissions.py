"""The Accessibility permission and the Fn/Globe key setting."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

ACCESSIBILITY_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
KEYBOARD_URL = "x-apple.systempreferences:com.apple.Keyboard-Settings.extension"

# System Settings > Keyboard > "Press 🌐 key to" (defaults domain com.apple.HIToolbox, key AppleFnUsageType)
FN_USAGE = {0: "Do Nothing", 1: "Change Input Source", 2: "Show Emoji & Symbols", 3: "Start Dictation"}


def is_trusted(prompt: bool = False) -> bool:
    """Accessibility permission for this app. ``prompt`` shows macOS's own request dialog once."""
    try:
        import ApplicationServices as AS
        if prompt:
            key = getattr(AS, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt")
            return bool(AS.AXIsProcessTrustedWithOptions({key: True}))
        return bool(AS.AXIsProcessTrusted())
    except Exception:
        log.exception("could not query the Accessibility permission")
        return False


def open_settings(url: str = ACCESSIBILITY_URL) -> None:
    try:
        subprocess.Popen(["/usr/bin/open", url])
    except OSError as e:
        log.warning("could not open System Settings: %s", e)


def fn_key_action() -> str | None:
    """What macOS does on a press of Fn/Globe alone, or None when the setting is not stored (default)."""
    try:
        from CoreFoundation import CFPreferencesCopyAppValue
        value = CFPreferencesCopyAppValue("AppleFnUsageType", "com.apple.HIToolbox")
    except Exception:
        log.exception("could not read the Fn key setting")
        return None
    if value is None:
        return None
    try:
        return FN_USAGE.get(int(value), f"unknown ({int(value)})")
    except (TypeError, ValueError):
        return None
