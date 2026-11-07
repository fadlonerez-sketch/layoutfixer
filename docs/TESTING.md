# Development and testing

## Commands

```
build_exe.bat           venv + tests + PyInstaller + verification  ->  dist\LayoutFixer.exe
run_tests.bat           run the tests (pytest)
run.bat                 run from source
python main.py --selftest report.json     self-test a build on this PC (changes nothing)
python tools\verify_build.py [exe]        exe self-test + tray start-up check (shortcuts disabled)
```

```
layoutfixer/
  keymap.py        physical key table (US / Hebrew)
  converter.py     strict key-for-key conversion; direction from the active layout (pure)
  engine.py        one conversion end to end + dispatcher (one at a time, cooldown)
  targets/         native_edit (Win32 messages), uia_target (UI Automation), clipboard_target (fallback)
  paste.py         clipboard paste with verification; clipboard.py backup/restore
  hotkeys.py       shortcut parsing + RegisterHotKey thread + fallback logic
  win/             ctypes API, focus/privilege, keyboard layouts, SendInput
  win_env.py       picks the strategy for the focused control
  app.py, ui/      tray, settings window, notification
  selftest.py      --selftest
tests/             pytest; tests/hosts/ are hidden test windows in separate processes
```

The tests never press real keys and never touch the real clipboard. Real-Windows tests use hidden
Win32 Edit/RichEdit controls and an off-screen Qt window in separate processes. Each test file's
docstring says which parts are real and which are simulated. An opt-in real clipboard round trip runs
with `set LAYOUTFIXER_REAL_CLIPBOARD_TESTS=1`.

## Pure and simulated subset (CI)

`.github/workflows/ci.yml` runs `ruff check .` and only the tests that need no real hotkey, keystroke,
keyboard layout, clipboard, registry or UI Automation target. They include the macOS logic tests,
which use fakes and run on Windows:

```bat
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python -m pytest tests/test_converter.py tests/test_mapping.py tests/test_clipboard_win32_logic.py tests/test_mac_keymap.py tests/test_mac_hotkeys.py tests/test_mac_env.py tests/test_engine.py tests/test_one_press.py tests/test_clipboard.py --deselect tests/test_engine.py::test_field_found_after_chromium_builds_its_accessibility_tree --deselect tests/test_engine.py::test_no_text_field_gives_up_after_the_settle_time --deselect tests/test_engine.py::test_focus_moving_elsewhere_stops_the_retries
```

On 2026-11-07 (Python 3.14.5, PySide6 6.12.0): **197 passed, 1 skipped** (the opt-in real-clipboard test).

## Full suite

`run_tests.bat` runs the full suite, including the real-Windows tests below, plus 1 opt-in test. What they cover:

* **Real Windows:** the key table is compared with the US and Hebrew layouts installed on the PC.
  Real cross-process window messages to standard Edit/RichEdit controls cover whole field, selection,
  CRLF/emoji offsets, password and read-only refusal, undo, and changed-text refusal. The same runs
  against Windows 11 Notepad's own editor class (`RichEditD2DPT`, from a copy of Notepad's
  `riched20.dll` in a hidden window), including the real keyboard-layout switch.
  **Real Chrome** (`tests/test_chrome_real.py`) runs on a hidden Windows desktop with a throw-away
  profile: input, textarea and contenteditable fields, whole field and selection only, through the
  real engine and UI Automation. Only the Ctrl+V there is simulated. Real UI
  Automation runs against Qt line, plain and rich text edits, including a picture inside the text.
  Also real: switching the Windows input language of a window and checking it, RegisterHotKey
  registration and conflict detection (Ctrl+Space included, released at once), the start-at-login
  registry entry (in a test key), and process integrity checks.
* **Simulated:** the Ctrl+C/Ctrl+V keystrokes, the clipboard (a fake with Windows-like sequence
  numbers), hotkey presses (WM_HOTKEY is posted to the hotkey thread), and the focused window.

Not covered by automated tests: pressing the real shortcut, real Ctrl+V into real apps (Chrome, Word,
Teams…), and the real clipboard backup/restore. Check those by hand:

### Manual checklist (about 3 minutes)

1. Start `LayoutFixer.exe`. The tray icon appears and the notification names the shortcut.
2. Notepad, keyboard on English: type `akuo' nv eurv?`, press Ctrl+Space → `שלום, מה קורה?`. Typing
   continues in Hebrew. Press Ctrl+Z → the original text is back.
3. Notepad: type `hello world`, select only `world`, press Ctrl+Space → only that word changes.
4. Chrome or Edge, a search box or a chat box: repeat step 2. Then type `יקךךם` with the keyboard on
   Hebrew and press Ctrl+Space → `hello`, and the keyboard is now English.
5. Copy an image or some formatted text, run step 4 again, then paste somewhere → your original
   clipboard is still there.
6. Click on a web page outside any input box and press Ctrl+Space → a notification says nothing can
   be changed, and the page stays as it was.
7. Press Ctrl+Space twice quickly → it converts once.
8. Tray > uncheck Enabled → Ctrl+Space works normally in other apps again.
