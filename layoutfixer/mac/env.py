"""The real macOS environment for the engine (the counterpart of win_env.WindowsEnvironment)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from ..config import Settings
from ..converter import Direction
from ..env_types import SwitchResult
from ..paste import ClipboardPaster
from ..targets.base import TargetError, TextTarget, Unsupported
from ..targets.clipboard_target import ClipboardSelectionTarget
from . import layouts as mlayouts
from .ax_target import TEXT_ROLES, AXTarget

log = logging.getLogger(__name__)

TERMINAL_BUNDLES = {"com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable", "dev.warp.Warp",
                    "net.kovidgoyal.kitty", "io.alacritty", "org.alacritty", "com.github.wez.wezterm",
                    "co.zeit.hyper", "com.mitchellh.ghostty", "org.tabby", "com.panic.Prompt3"}
# ⌘C / ⌘V there act on files, not text: never use the clipboard fallback.
NO_FALLBACK_BUNDLES = {"com.apple.finder"}
CHROMIUM_BUNDLE_PREFIXES = ("com.google.Chrome", "org.chromium.", "com.microsoft.edgemac", "com.brave.Browser",
                            "company.thebrowser.", "com.vivaldi.", "com.operasoftware.", "com.electron.")

PERMISSION_MESSAGE = ("Layout Fixer needs the Accessibility permission: System Settings > Privacy & Security > "
                      "Accessibility > turn on Layout Fixer")
UNSUPPORTED_MESSAGE = ("Layout Fixer can't read the text in this app. Select the text and try again, "
                       "or use a different app")
SECURE_INPUT_MESSAGE = ("Secure keyboard entry is on (a password field or an app such as Terminal turned it on) "
                        "- nothing was changed")

AX_SETTLE_S = 1.0   # how long Chromium/Electron apps get to build their accessibility tree
AX_RETRY_S = 0.15
ARMED_MAX_AGE_S = 10.0
SWITCH_TIMEOUT_S = 0.6


@dataclass(frozen=True)
class MacFocus:
    pid: int
    process_name: str            # app name
    bundle_id: str
    class_name: str              # AX role of the focused element ("" when there is none)
    has_caret: bool              # the focused element reports a text selection / caret
    element: object = field(default=None, compare=False, hash=False, repr=False)


class MacEnvironment:
    """Used from the dispatcher's worker thread. ``call_main`` / ``post_main`` run a function on the
    main thread (keyboard-layout calls must run there)."""

    def __init__(self, call_main: Callable, post_main: Callable, ax=None, tis=None, clipboard=None, keyboard=None,
                 app_info: Callable[[int], tuple[str, str]] | None = None, frontmost_pid: Callable[[], int] | None = None):
        if keyboard is None:
            from .keyboard import MacKeyboard
            keyboard = MacKeyboard()
        if clipboard is None:
            from .clipboard import MacClipboard
            clipboard = MacClipboard()
        if tis is None:
            from . import tis as _tis
            tis = _tis
        self.call_main = call_main
        self.post_main = post_main
        self.keyboard = keyboard
        self.clipboard = clipboard
        self.tis = tis
        self._ax = ax
        self._app_info = app_info or _app_info
        self._frontmost_pid = frontmost_pid or _frontmost_pid
        self._armed: tuple[float, object] | None = None
        self._source = None                       # layout of the press in progress
        self._lists: tuple[list, list] | None = None
        self._tables_cache: dict[tuple, tuple[dict, dict]] = {}
        self._ax_enabled_pids: set[int] = set()

    def ax(self):
        if self._ax is None:
            from .ax import AXClient
            self._ax = AXClient()
        return self._ax

    # ------------------------------------------------------------------ keyboard layout
    def note_chord_armed(self) -> None:
        """Called from the event tap when the keys of a modifier-only shortcut are all down: remember the
        active layout now, before macOS may act on the Fn/Globe key release (e.g. switch the input source)."""
        def snap():
            self._armed = (time.monotonic(), self.tis.current_source())
        self.post_main(snap)

    def current_lang(self, f: MacFocus) -> str | None:
        armed, self._armed = self._armed, None
        if armed is not None and time.monotonic() - armed[0] < ARMED_MAX_AGE_S and armed[1] is not None:
            source = armed[1]
            log.info("layout: taken when the shortcut keys went down")
        else:
            source = self.call_main(self.tis.current_source)
        self._source = source
        self._lists = None
        if source is None:
            return None
        log.info("layout: %s (%s)", source.id, source.lang)
        return source.lang

    def _sources(self) -> tuple[list, list]:
        """(enabled, installed) keyboard input sources, read once per press."""
        if self._lists is None:
            self._lists = self.call_main(lambda: (self.tis.list_sources(False), self.tis.list_sources(True)))
        return self._lists

    def _pair_for(self, target_lang: str) -> mlayouts.Pair | None:
        if self._source is None:
            return None
        enabled, installed = self._sources()
        return mlayouts.choose_pair(self._source, enabled, installed, target_lang)

    def _source_layout_id(self, lang: str) -> str:
        """Layout whose keys the text was typed with: the active one, or (forced direction) one of ``lang``."""
        if self._source is not None and self._source.lang == lang:
            if self._source.is_layout:
                return self._source.id
            current = self.call_main(self.tis.current_layout)  # an input method: the layout behind it
            return current.id if current is not None else ""
        enabled, installed = self._sources()
        layout = mlayouts.pick_layout(enabled, lang) or mlayouts.pick_layout(installed, lang)
        return layout.id if layout else ""

    def key_tables(self, direction: Direction) -> tuple[dict, dict] | None:
        pair = self._pair_for(direction.target_lang)
        if pair is None:
            return None
        src_id = self._source_layout_id(direction.source_lang)
        key = (src_id, pair.target_id, direction.source_lang)
        cached = self._tables_cache.get(key)
        if cached is not None:
            return cached
        kbd, src_data, dst_data = self.call_main(lambda: (
            self.tis.keyboard_type(), self.tis.layout_data(src_id) if src_id else None,
            self.tis.layout_data(pair.target_id) if pair.target_id else None))
        read_src = self.tis.KeyTranslator(src_data, kbd).char if src_data else None
        read_dst = self.tis.KeyTranslator(dst_data, kbd).char if dst_data else None
        log.info("key tables: %s -> %s (%s%s)", src_id or "built-in", pair.target_id or "built-in",
                 "read from macOS" if read_src and read_dst else "partly built-in",
                 "" if pair.target else "; target layout not in the input menu")
        tables = mlayouts.tables_for(direction.source_lang, read_src, read_dst)
        self._tables_cache[key] = tables
        return tables

    def switch_layout(self, f: MacFocus, lang: str) -> SwitchResult:
        pair = self._pair_for(lang)
        before = self._source.lang if self._source else None
        if pair is None or pair.target is None:
            name = mlayouts.LANG_LABEL[lang]
            return SwitchResult(False, f"no {name} keyboard is added in System Settings > Keyboard > Input Sources",
                                before, before)
        target = pair.target
        current = self.call_main(self.tis.current_source)
        if current is not None and current.lang == lang:
            return SwitchResult(True, "already active", before, lang)
        if not self.call_main(lambda: self.tis.select(target.id)):
            return SwitchResult(False, "macOS refused to change the input source", before, before)
        # The new source may only show once the main run loop has handled the change notification:
        # check from here, letting the main thread run in between.
        deadline = time.monotonic() + SWITCH_TIMEOUT_S
        while True:
            after = self.call_main(self.tis.current_source)
            if after is not None and after.lang == lang:
                return SwitchResult(True, "switched", before, lang)
            if time.monotonic() >= deadline:
                return SwitchResult(False, "the input source did not change", before, after.lang if after else None)
            time.sleep(0.03)

    # ------------------------------------------------------------------ focus and targets
    def focus(self) -> MacFocus | None:
        ax = self.ax()
        app = ax.focused_app()
        pid = ax.pid(app) if app is not None else None
        if pid is None:
            pid = self.call_main(self._frontmost_pid)
            app = ax.app(pid) if pid else None
        if not pid:
            return None
        el = ax.focused_element(app)
        role = ax.get(el, "AXRole") if el is not None else None
        has_caret = el is not None and ax.get_range(el) is not None
        name, bundle = self._app_info(pid)
        return MacFocus(pid, name, bundle, str(role or ""), has_caret, el)

    def is_blocked(self, f: MacFocus) -> bool:
        return False  # macOS has no equivalent of Windows' integrity levels between normal apps

    def wait_responsive(self, pid: int, timeout_s: float = 5.0) -> bool:
        """True once the app answers Accessibility requests again (False if it stays hung)."""
        ax = self.ax()
        app = ax.app(pid)
        deadline = time.monotonic() + timeout_s
        while True:
            if ax.get(app, "AXRole") is not None:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def make_target(self, f: MacFocus, settings: Settings) -> TextTarget:
        ax = self.ax()
        if not ax.trusted():
            raise TargetError(PERMISSION_MESSAGE)
        if f.bundle_id in TERMINAL_BUNDLES:
            raise Unsupported("Terminal windows are not supported")
        target, role = self._ax_target(f)
        if target is not None:
            return target
        textish = f.has_caret or role in TEXT_ROLES or f.class_name in TEXT_ROLES
        log.info("no readable text field (caret=%s, role=%s, clipboard fallback=%s)", f.has_caret, role,
                 settings.clipboard_fallback)
        if settings.clipboard_fallback and textish and f.bundle_id not in NO_FALLBACK_BUNDLES:
            if self.call_main(self.tis.secure_input):
                raise TargetError(SECURE_INPUT_MESSAGE)
            return ClipboardSelectionTarget(self.clipboard, self.keyboard,
                                            wait_idle=lambda: self.wait_responsive(f.pid))
        raise Unsupported(UNSUPPORTED_MESSAGE)

    def _enable_app_accessibility(self, f: MacFocus) -> None:
        """Chromium and Electron build their web-content accessibility tree only when asked to."""
        if f.pid in self._ax_enabled_pids:
            return
        self._ax_enabled_pids.add(f.pid)
        ax = self.ax()
        app = ax.app(f.pid)
        manual = ax.set(app, "AXManualAccessibility", True)          # Electron (and Chromium)
        enhanced = False
        if f.bundle_id.startswith(CHROMIUM_BUNDLE_PREFIXES):
            enhanced = ax.set(app, "AXEnhancedUserInterface", True)  # Chrome, Edge, Brave, Arc...
        log.info("AX: asked the app to expose its text (manual=%s, enhanced=%s)", manual, enhanced)

    def _ax_target(self, f: MacFocus) -> tuple[AXTarget | None, str | None]:
        ax = self.ax()
        deadline = time.monotonic() + AX_SETTLE_S
        attempt = 0
        role = None
        while True:
            attempt += 1
            el = ax.focused_element(ax.app(f.pid))
            if el is not None:
                paster = ClipboardPaster(self.clipboard, self.keyboard, wait_idle=lambda: self.wait_responsive(f.pid))
                target = AXTarget(ax, el, paster, bundle_id=f.bundle_id)
                try:
                    target.check_editable()  # password / read-only / disabled: TargetError, stops here
                    log.info("AX: text field found (role %s, attempt %d)", target.role, attempt)
                    return target, target.role
                except Unsupported as e:
                    role = target.role
                    log.info("AX attempt %d: %s (role %s)", attempt, e, role)
            else:
                log.info("AX attempt %d: no focused element", attempt)
            if attempt == 1:
                self._enable_app_accessibility(f)
            if time.monotonic() >= deadline or self._focused_pid() != f.pid:
                return None, role
            time.sleep(AX_RETRY_S)

    def _focused_pid(self) -> int | None:
        ax = self.ax()
        app = ax.focused_app()
        return ax.pid(app) if app is not None else None


def _app_info(pid: int) -> tuple[str, str]:
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return "", ""
        return str(app.localizedName() or ""), str(app.bundleIdentifier() or "")
    except Exception:  # noqa: BLE001
        return "", ""


def _frontmost_pid() -> int:
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(app.processIdentifier()) if app is not None else 0
