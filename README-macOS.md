# Layout Fixer for macOS

The same tool as on Windows (see README.md): a shortcut converts the focused field's text key-for-key
between the English and Hebrew keyboard layouts, replaces it in place and switches the keyboard
language. On a Mac the shortcut is **⌘ + Fn** (hold Command, press Fn/🌐, release both).

The package for a Mac user is `dist/mac/LayoutFixer-macOS.zip`, built with `build_mac.bat` (prebuilt packages
are not published yet): "Layout Fixer.app" (universal:
Apple silicon and Intel, macOS 12+) and "Read Me First.txt" with install and usage instructions.
Nothing to install besides the app; no Python, Xcode or Homebrew needed.

> **Status:** built and checked on Windows only. No part of it has run on a real Mac yet.
> See "What has been verified" and the manual checklist below.

## What is the same, what is Mac-specific

The engine (`engine.py`), the conversion rules (`converter.py`), the clipboard guard, the paste
verification, the settings, the tray menu, the settings window and the notifications are shared.

| | Windows | macOS (`layoutfixer/mac/`) |
|---|---|---|
| Shortcut | `RegisterHotKey` (Ctrl+Space) | Quartz event tap: modifier-only chord **⌘+Fn** (`mac/hotkeys.py`) |
| Read/write the field | Win32 edit messages, UI Automation | Accessibility API (AXValue, AXSelectedTextRange, AXSelectedText) (`mac/ax_target.py`) |
| Paste fallback | Ctrl+C / Ctrl+V via SendInput | ⌘C / ⌘V via CGEvent (`mac/keyboard.py`) |
| Clipboard backup | Win32 clipboard, all formats | NSPasteboard, all items and types; nspasteboard.org markers so clipboard managers skip our text |
| Active layout / switch | `GetKeyboardLayout` / `WM_INPUTLANGCHANGEREQUEST` | Text Input Sources: `TISCopyCurrentKeyboardInputSource` / `TISSelectInputSource`, on the main thread (`mac/tis.py`) |
| Key table | fixed Windows US/Hebrew table (`keymap.py`) | read from the Mac's own installed layouts with UCKeyTranslate; built-in Mac table as fallback (`mac/keymap_mac.py`) |
| Start at login | `HKCU\...\Run` | LaunchAgent `~/Library/LaunchAgents/local.layoutfixer.LayoutFixer.plist` |
| Settings / logs | `%APPDATA%\LayoutFixer` | `~/Library/Application Support/LayoutFixer` |
| Not touched | password fields, terminals, elevated apps | password fields (AXSecureTextField), terminal apps, Finder (no clipboard fallback there) |

There is no translation provider and no API key: the conversion is a local key table, as on Windows.

### Why the Mac key table differs

macOS layouts are not the Windows ones. The default Mac "Hebrew" layout types `׳` (geresh) on W
where Windows types `'`, puts a rafe on the backslash key, has no Latin capitals on Shift, and
"Hebrew – QWERTY" is phonetic. To keep the rule "what the same keys type on the other layout", the
Mac version reads every key of the active layout and of the layout it switches to (UCKeyTranslate,
the counterpart of `ToUnicodeEx`). The built-in fallback (`BUILTIN_ROWS`, from Unicode CLDR's macOS
data) is used only for a layout that cannot be read. The conversion stays strict 1:1 per character.

## ⌘ + Fn: what macOS allows

* **The system hotkey API cannot do it.** `RegisterEventHotKey` (Carbon) needs a non-modifier key and
  has no Fn modifier. So ⌘+Fn is detected with a **Quartz event tap**, as dictation apps that use Fn
  do. An event tap needs the **Accessibility** permission (the same permission the app needs anyway
  to read and change text), granted once in System Settings > Privacy & Security > Accessibility.
* **When it fires:** when both keys have been released and nothing else (key or mouse button) was
  pressed in between, and exactly ⌘ and Fn were held. So ⌘C, ⌘+Fn+← (= ⌘+Home) or ⌘+click never
  trigger it. Modifier key events are never swallowed.
* **Only keyboards that report Fn.** MacBook keyboards and Apple Magic Keyboards send Fn to macOS;
  most third-party keyboards handle Fn in their own firmware and the Mac never sees it. For those,
  Settings has **"Also use (keyboards without Fn)"** - a second, regular shortcut (e.g.
  Ctrl+Option+Space) active at the same time. ⌘+Fn stays the main shortcut; nothing is substituted
  silently.
* **The 🌐 key's own action.** macOS gives Fn/🌐 an action (System Settings > Keyboard > "Press 🌐 key
  to": input source, emoji, dictation). An app cannot reliably suppress it. If ⌘+Fn also triggers
  that action, set it to "Do Nothing" (Settings shows the current value). Because macOS may switch
  the input source when Fn is released, the app records the active layout **when ⌘ and Fn are both
  down** and uses that for the direction, so such a switch cannot reverse the conversion.
* **Secure input:** while a password field (or Terminal's Secure Keyboard Entry) has secure input
  on, macOS hides key events from event taps; the shortcut does nothing then, by design.

## The app bundle

Built on Windows by `tools/build_mac_app.py` without compiling anything:

* `Contents/MacOS/LayoutFixer` is py2app 0.28.10's prebuilt universal launcher (MIT). It loads
  Python *into the app's own process*, so macOS knows the running app as "Layout Fixer" (its entry
  in the Accessibility list, LSUIElement menu-bar mode, its icon). A shell script that exec'd Python
  would make macOS see "python3.13" instead.
* `Contents/Frameworks/libpython3.13.dylib` and the standard library come from
  python-build-standalone 3.13.18; the arm64 and x86_64 builds are merged into universal binaries
  by `tools/macho.py` (slices copied byte for byte, so Apple-silicon signatures stay valid).
* PySide6-Essentials **6.9.3** (QtCore, QtGui, QtWidgets, QtNetwork + their frameworks only) and
  PyObjC 12.2.2. PySide6 6.9 is used, not 6.12 as on Windows, because the 6.10/6.11 binding modules
  are built for macOS 15 and 6.12's for macOS 26, whatever the wheels' tags say; 6.9 runs on macOS 12+.
  The whole test suite also passes on Python 3.13 + PySide6 6.9.3.
* All downloads are pinned and hash-checked (`requirements-mac.txt`, `build_mac_app.py`).
* The app is **not code-signed with an Apple Developer ID and not notarized** (that needs a paid
  Apple account and a Mac). The first start therefore needs one of the two Gatekeeper steps in
  "Read Me First.txt".

### Build and check

```
build_mac.bat                                    venv (Python 3.13) + tests + build + verification
build\venv313\Scripts\python tools\build_mac_app.py     build only -> dist\mac\LayoutFixer-macOS.zip
build\venv313\Scripts\python tools\verify_mac_bundle.py check the zip (exit code 0 = all passed)
```

## What has been verified (on Windows)

* **Unit and flow tests** (`tests/test_mac_*.py`, 89 tests) with simulated macOS: Cmd+Fn chord
  logic and every way it must *not* fire, shortcut parsing and recording, the Accessibility target
  (Cocoa fields via AXSelectedText; Chromium/Electron via async selection + verified ⌘V; Firefox;
  apps that ignore AX writes; password, read-only and disabled fields; emoji offsets in UTF-16 units;
  embedded objects never overwritten), the environment (permission missing, terminals, Finder,
  secure input, Chromium accessibility enabling, layout taken when the keys went down, Hebrew not in
  the input menu, Hebrew-QWERTY, forced directions), the pasteboard backup/restore, the LaunchAgent,
  the main-thread runner, the tray app and settings window in Mac mode, the boot script.
* **The complete suite (Windows + Mac logic) on Python 3.14/PySide6 6.12 and on Python 3.13/PySide6 6.9.3.**
* **The bundle** (`tools/verify_mac_bundle.py`, ~1000 checks): layout and Info.plist; the
  launcher's requirements (libpython exports every function it looks up, PYTHONHOME layout); every
  Mach-O file is universal, its arm64 code signature verifies page by page, its minimum macOS is
  ≤ 12.0 and every library it links is present; the C modules used are built into libpython; every
  module the Mac code imports is in the bundle; every PyObjC function/constant it uses exists in
  the bundled PyObjC (the AXValue wrappers' call signatures were checked against PyObjC's C source);
  the .py files compile and the .pyc files are valid for Python 3.13. `tests/test_mac_bundle_tools.py`
  proves the verifier catches a changed byte, a missing library, a missing key and a wrong name.

**Not verified - needs a Mac:** that the app starts; that macOS delivers Fn to the event tap
and the chord fires; the Accessibility prompt and list entry; AX reads/writes in real apps; real
⌘V and pasteboard restore; the input-source switch; UCKeyTranslate on the real layouts (the
self-test reports these); whether ⌘+Fn triggers the 🌐 action; Gatekeeper's exact dialogs.

## Manual checklist on a Mac (about 5 minutes)

1. Install as in "Read Me First.txt". Start the app: no Dock icon, an אA icon in the menu bar, the
   Accessibility prompt names **Layout Fixer**.
2. Turn the permission on. Within ~2 s a note says "Layout Fixer is running - press Cmd+Fn".
3. Self-test: `"/Applications/Layout Fixer.app/Contents/MacOS/LayoutFixer" --selftest ~/Desktop/lf.json`
   - `"ok": true`; look at `differences_from_builtin_table` and `fn_key_action`.
4. TextEdit, keyboard on ABC/U.S.: type `akuo' nv eurv?`, ⌘+Fn → `שלום, מה קורה?`, keyboard now
   Hebrew. ⌘Z restores the text. ⌘+Fn again converts back.
5. Select one word only, ⌘+Fn → only that word changes, it stays selected.
6. Safari and Chrome: a search box and a textarea - repeat 4. Copy an image first; afterwards paste
   → the image is still on the clipboard.
7. ⌘C, ⌘+Fn+←, ⌘+click in a field: nothing is converted.
8. Notes, Messages, VS Code or Slack (Electron): repeat 4.
9. A password field: the note says it is not changed. Terminal: "not supported".
10. Settings > Also use: record Ctrl+Option+Space; it converts too. Uncheck Enabled: nothing converts.
11. Settings > Start at login, log out and in: the app is running.

## Known limitations (macOS)

* ⌘+Fn needs a keyboard that reports Fn (see above); otherwise use the alternative shortcut.
* Without Developer ID signing, every new copy of the app needs the Gatekeeper step and the
  Accessibility switch again (macOS ties the permission to that copy).
* Chromium-based apps get `AXEnhancedUserInterface` / `AXManualAccessibility` set on the first press
  so they expose their web content; Chrome then keeps its accessibility mode on until it restarts.
* Apps without accessibility support work only through the selection + ⌘C/⌘V fallback, or not at all.
* As on Windows: formatting of the changed characters follows the insertion point, and the whole
  field is limited to 10,000 characters without a selection.
