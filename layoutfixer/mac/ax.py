"""The macOS Accessibility API (AXUIElement, HIServices) through PyObjC - the Mac counterpart of uia.py.

Every call returns None / False on an AX error instead of raising: apps answer
slowly, refuse attributes, or quit in the middle of a press. Ranges are in
UTF-16 code units (NSString indices), like Windows edit controls.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

AX_SUCCESS = 0
AX_RANGE_TYPE = 4  # kAXValueCFRangeType


class AXClient:
    def __init__(self, timeout_s: float = 1.0):
        import ApplicationServices as AS
        self.AS = AS
        self.range_type = getattr(AS, "kAXValueCFRangeType", AX_RANGE_TYPE)
        self.system = AS.AXUIElementCreateSystemWide()
        # A hung app would otherwise block each call for 6 s (the default).
        AS.AXUIElementSetMessagingTimeout(self.system, timeout_s)
        self.timeout_s = timeout_s

    def trusted(self) -> bool:
        return bool(self.AS.AXIsProcessTrusted())

    def get(self, el, attr: str):
        if el is None:
            return None
        try:
            err, value = self.AS.AXUIElementCopyAttributeValue(el, attr, None)
        except Exception as e:  # noqa: BLE001
            log.debug("AX get %s failed: %s", attr, e)
            return None
        return value if err == AX_SUCCESS else None

    def names(self, el) -> list[str]:
        try:
            err, names = self.AS.AXUIElementCopyAttributeNames(el, None)
        except Exception:  # noqa: BLE001
            return []
        return [str(n) for n in names] if err == AX_SUCCESS and names else []

    def settable(self, el, attr: str) -> bool:
        try:
            err, ok = self.AS.AXUIElementIsAttributeSettable(el, attr, None)
        except Exception:  # noqa: BLE001
            return False
        return err == AX_SUCCESS and bool(ok)

    def set(self, el, attr: str, value) -> bool:
        try:
            return self.AS.AXUIElementSetAttributeValue(el, attr, value) == AX_SUCCESS
        except Exception as e:  # noqa: BLE001
            log.debug("AX set %s failed: %s", attr, e)
            return False

    def get_range(self, el, attr: str = "AXSelectedTextRange") -> tuple[int, int] | None:
        """(location, length) in UTF-16 units."""
        value = self.get(el, attr)
        if value is None:
            return None
        try:
            ok, rng = self.AS.AXValueGetValue(value, self.range_type, None)
        except Exception:  # noqa: BLE001
            return None
        if not ok or rng is None:
            return None
        try:
            return int(rng.location), int(rng.length)
        except AttributeError:
            return int(rng[0]), int(rng[1])

    def set_range(self, el, location: int, length: int, attr: str = "AXSelectedTextRange") -> bool:
        try:
            value = self.AS.AXValueCreate(self.range_type, (location, length))
        except Exception as e:  # noqa: BLE001
            log.debug("AXValueCreate failed: %s", e)
            return False
        return value is not None and self.set(el, attr, value)

    def pid(self, el) -> int | None:
        try:
            err, pid = self.AS.AXUIElementGetPid(el, None)
        except Exception:  # noqa: BLE001
            return None
        return int(pid) if err == AX_SUCCESS else None

    def app(self, pid: int):
        el = self.AS.AXUIElementCreateApplication(pid)
        self.AS.AXUIElementSetMessagingTimeout(el, self.timeout_s)
        return el

    def focused_app(self):
        return self.get(self.system, "AXFocusedApplication")

    def focused_element(self, app=None):
        el = self.get(app, "AXFocusedUIElement") if app is not None else None
        return el if el is not None else self.get(self.system, "AXFocusedUIElement")
