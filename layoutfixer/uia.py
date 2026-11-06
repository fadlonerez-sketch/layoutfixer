"""Thin UI Automation client (comtypes). Create and use it on one thread only."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

UIA_ValuePatternId = 10002
UIA_TextPatternId = 10014
UIA_IsReadOnlyAttributeId = 40015
UIA_EditControlTypeId = 50004
UIA_DocumentControlTypeId = 50030
TextUnit_Character = 0
Endpoint_Start = 0
Endpoint_End = 1


def load_module():
    """The comtypes wrapper for UIAutomationCore (pre-generated in builds, generated on first use otherwise)."""
    try:
        from comtypes.gen import UIAutomationClient  # type: ignore[attr-defined]
        return UIAutomationClient
    except ImportError:
        import comtypes.client
        return comtypes.client.GetModule("UIAutomationCore.dll")


class UiaClient:
    def __init__(self, timeout_ms: int = 2000):
        import sys
        import threading
        if "comtypes" not in sys.modules and threading.current_thread() is not threading.main_thread():
            sys.coinit_flags = 0  # COINIT_MULTITHREADED for the worker (comtypes initialises COM on import)
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # this thread already has COM (comtypes initialises the main thread on import)
        self.mod = load_module()
        self.client = comtypes.client.CreateObject(self.mod.CUIAutomation, interface=self.mod.IUIAutomation)
        try:
            c2 = self.client.QueryInterface(self.mod.IUIAutomation2)
            c2.ConnectionTimeout = timeout_ms
            c2.TransactionTimeout = timeout_ms
        except Exception:  # IUIAutomation2 needs Windows 8+; keep the defaults otherwise
            log.debug("IUIAutomation2 timeouts not available")

    def focused_element(self):
        try:
            el = self.client.GetFocusedElement()
        except Exception as e:  # COMError when nothing / an inaccessible element has the focus
            log.info("GetFocusedElement failed: %s", e)
            return None
        return el if el else None

    def element_from_handle(self, hwnd: int):
        return self.client.ElementFromHandle(hwnd)

    def text_pattern(self, el):
        try:
            p = el.GetCurrentPattern(UIA_TextPatternId)
            return p.QueryInterface(self.mod.IUIAutomationTextPattern) if p else None
        except Exception:
            return None

    def value_pattern(self, el):
        try:
            p = el.GetCurrentPattern(UIA_ValuePatternId)
            return p.QueryInterface(self.mod.IUIAutomationValuePattern) if p else None
        except Exception:
            return None
