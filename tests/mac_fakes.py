"""Test doubles for the macOS layer. Nothing here touches macOS - these tests run on any OS.

FakeAX stands in for mac.ax.AXClient (the Accessibility API), FakeTIS for
mac.tis (input sources + UCKeyTranslate), FakePasteboard for NSPasteboard.
Their behaviour follows what the Mac APIs document; that the real APIs behave
this way is only checked on a Mac (README-macOS.md, manual checklist).
"""

from __future__ import annotations

from layoutfixer.mac.keymap_mac import BUILTIN_ROWS
from layoutfixer.mac.tis import SourceInfo
from layoutfixer.textindex import from_units, to_units


class FakeApp:
    def __init__(self, pid: int):
        self.pid = pid

    def __eq__(self, other):
        return isinstance(other, FakeApp) and other.pid == self.pid

    def __hash__(self):
        return hash(self.pid)


class FakeElement:
    """A text field. Ranges are UTF-16 units, as on macOS."""

    def __init__(self, value: str = "", sel: tuple[int, int] | None = None, role: str = "AXTextField",
                 subrole: str | None = None, enabled: bool = True,
                 settable: tuple[str, ...] = ("AXValue", "AXSelectedTextRange", "AXSelectedText"),
                 chromium: bool = False, select_delay: int = 0, ignore_selected_text: bool = False,
                 never_select: bool = False):
        self.value = value
        if sel is None:
            n = to_units(value, len(value))
            sel = (n, 0)
        self.sel = sel
        self.role, self.subrole, self.enabled = role, subrole, enabled
        self.settable_attrs = set(settable)
        self.chromium = chromium
        self.select_delay = select_delay        # reads of the range before a requested selection shows
        self._pending: tuple[tuple[int, int], int] | None = None
        self.ignore_selected_text = ignore_selected_text
        self.never_select = never_select
        self.selected_text_writes: list[str] = []
        self.range_writes: list[tuple[int, int]] = []

    # python-index helpers
    def _slice(self, loc: int, length: int) -> tuple[int, int]:
        return from_units(self.value, loc), from_units(self.value, loc + length)

    def selected_text(self) -> str:
        a, b = self._slice(*self.sel)
        return self.value[a:b]

    def replace_selection(self, piece: str) -> None:
        a, b = self._slice(*self.sel)
        self.value = self.value[:a] + piece + self.value[b:]
        self.sel = (to_units(self.value, a + len(piece)), 0)

    def read_range(self) -> tuple[int, int]:
        if self._pending is not None:
            rng, left = self._pending
            if left <= 0:
                self.sel = rng
                self._pending = None
            else:
                self._pending = (rng, left - 1)
        return self.sel

    def request_range(self, rng: tuple[int, int]) -> None:
        self.range_writes.append(rng)
        if self.never_select:
            return
        if self.select_delay:
            self._pending = (rng, self.select_delay)
        else:
            self.sel = rng


class FakeAX:
    def __init__(self, element: FakeElement | None = None, trusted: bool = True, pid: int = 100,
                 element_after_enable: FakeElement | None = None, hung: bool = False):
        self.element = element
        self._trusted = trusted
        self.focus_pid = pid
        self.element_after_enable = element_after_enable
        self.hung = hung
        self.app_attrs: dict[str, object] = {}

    def trusted(self) -> bool:
        return self._trusted

    def get(self, el, attr):
        if el is None or not self._trusted:
            return None
        if isinstance(el, FakeApp):
            if attr == "AXFocusedUIElement":
                return self.element
            if attr == "AXRole":
                return None if self.hung else "AXApplication"
            return self.app_attrs.get(attr)
        if el == "system":
            return FakeApp(self.focus_pid) if attr == "AXFocusedApplication" else None
        e: FakeElement = el
        if attr == "AXRole":
            return e.role
        if attr == "AXSubrole":
            return e.subrole
        if attr == "AXEnabled":
            return e.enabled
        if attr == "AXValue":
            return e.value
        if attr == "AXSelectedText":
            e.read_range()
            return e.selected_text()
        return None

    def names(self, el) -> list[str]:
        base = ["AXRole", "AXValue", "AXSelectedText", "AXSelectedTextRange"]
        return base + (["ChromeAXNodeId"] if getattr(el, "chromium", False) else [])

    def settable(self, el, attr) -> bool:
        return isinstance(el, FakeElement) and attr in el.settable_attrs

    def set(self, el, attr, value) -> bool:
        if isinstance(el, FakeApp):
            self.app_attrs[attr] = value
            if self.element_after_enable is not None:
                self.element = self.element_after_enable
            return True
        e: FakeElement = el
        if attr == "AXSelectedText" and attr in e.settable_attrs:
            e.selected_text_writes.append(value)
            if not e.ignore_selected_text:
                e.replace_selection(value)
            return True
        return False

    def get_range(self, el, attr="AXSelectedTextRange"):
        if not isinstance(el, FakeElement) or not self._trusted:
            return None
        return el.read_range()

    def set_range(self, el, location, length, attr="AXSelectedTextRange") -> bool:
        if not isinstance(el, FakeElement) or "AXSelectedTextRange" not in el.settable_attrs:
            return False
        el.request_range((location, length))
        return True

    def pid(self, el):
        return el.pid if isinstance(el, FakeApp) else None

    def app(self, pid):
        return FakeApp(pid)

    def focused_app(self):
        return self.get("system", "AXFocusedApplication")

    def focused_element(self, app=None):
        return self.get(app, "AXFocusedUIElement") if app is not None else None


def paste_into(element: FakeElement, clipboard):
    """FakeKeyboard.on_paste: what an app does on ⌘V."""
    def on_paste():
        element.replace_selection(clipboard.get_text() or "")
    return on_paste


# ------------------------------------------------------------------ input sources
def _layer(column_base: int) -> dict[int, tuple[str, str]]:
    return {r[0]: (r[column_base], r[column_base + 1]) for r in BUILTIN_ROWS}


# Fake layout data: what UCKeyTranslate would report for each key code (base, shift).
LAYOUTS: dict[str, dict[int, tuple[str, str]]] = {
    "com.apple.keylayout.ABC": _layer(1),
    "com.apple.keylayout.US": _layer(1),
    "com.apple.keylayout.Hebrew": _layer(3),
    # A deliberately different Hebrew layout, to prove the installed layout is what gets used.
    "com.apple.keylayout.Hebrew-QWERTY": {0: ("א", ""), 11: ("ב", ""), 2: ("ד", ""), 49: (" ", " "),
                                          4: ("ה", "ח"), 31: ("ו", "")},
}
LANGS = {"com.apple.keylayout.ABC": ("en",), "com.apple.keylayout.US": ("en",),
         "com.apple.keylayout.Hebrew": ("he",), "com.apple.keylayout.Hebrew-QWERTY": ("he",),
         "com.apple.keylayout.Russian": ("ru",)}


def source(sid: str, enabled: bool = True) -> SourceInfo:
    return SourceInfo(sid, sid.rsplit(".", 1)[-1], LANGS.get(sid, ("en",)), True, enabled, enabled)


class FakeTIS:
    def __init__(self, enabled=("com.apple.keylayout.ABC", "com.apple.keylayout.Hebrew"),
                 current="com.apple.keylayout.ABC", installed=None, select_ok: bool = True):
        self.enabled = list(enabled)
        self.installed = list(installed or (list(LAYOUTS) + ["com.apple.keylayout.Russian"]))
        self.current = current
        self.select_ok = select_ok
        self.selected: list[str] = []
        self.secure = False
        self.switch_delay = 0          # reads of the current source before a selected one shows
        self._pending: str | None = None

    def list_sources(self, include_all=False):
        ids = self.installed if include_all else self.enabled
        return [source(i, i in self.enabled) for i in ids]

    def current_source(self):
        if self._pending is not None:
            if self.switch_delay <= 0:
                self.current, self._pending = self._pending, None
            else:
                self.switch_delay -= 1
        return source(self.current)

    def current_layout(self):
        return source(self.current)

    def layout_data(self, sid):
        return sid.encode() if sid in LAYOUTS else None

    def keyboard_type(self):
        return 40

    def select(self, sid):
        self.selected.append(sid)
        if self.select_ok and sid in self.enabled:
            if self.switch_delay:
                self._pending = sid
            else:
                self.current = sid
            return True
        return False

    def secure_input(self):
        return self.secure

    class KeyTranslator:
        def __init__(self, data: bytes, kbd: int):
            self.layout = LAYOUTS[data.decode()]

        def char(self, keycode: int, shift: bool) -> str:
            return self.layout.get(keycode, ("", ""))[1 if shift else 0]


# ------------------------------------------------------------------ pasteboard
class FakeItem:
    def __init__(self):
        self.data: dict[str, bytes] = {}

    def types(self):
        return list(self.data)

    def dataForType_(self, t):
        return self.data.get(t)

    def setData_forType_(self, d, t):
        self.data[t] = bytes(d)

    def setString_forType_(self, s, t):
        self.data[t] = s.encode("utf-8")


class FakePasteboard:
    def __init__(self, items: list[dict[str, bytes]] | None = None):
        self.count = 1
        self.items: list[FakeItem] = []
        for d in items or []:
            it = FakeItem()
            it.data = dict(d)
            self.items.append(it)

    def changeCount(self):
        return self.count

    def pasteboardItems(self):
        return list(self.items)

    def clearContents(self):
        self.items = []
        self.count += 1
        return self.count

    def writeObjects_(self, items):
        self.items.extend(items)
        return True

    def stringForType_(self, t):
        for it in self.items:
            if t in it.data:
                return it.data[t].decode("utf-8")
        return None

    def external_copy(self, text: str):
        self.clearContents()
        it = FakeItem()
        it.setString_forType_(text, "public.utf8-plain-text")
        self.writeObjects_([it])
