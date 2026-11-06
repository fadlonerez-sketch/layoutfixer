# Layout Fixer - maintenance notes

Windows 10/11 tray app: Ctrl+Space converts the focused field's text between the US and Hebrew
keyboard layouts (physical keys), replaces it in place and switches the input language.
Python 3.14, PySide6, ctypes, comtypes (UI Automation). See README.md for behaviour.

## Commands

- Tests: `run_tests.bat` (or `.venv\Scripts\python -m pytest -q`)
- Build + verify: `build_exe.bat` -> `dist\LayoutFixer.exe` (PyInstaller one-file); `tools\verify_build.py`
- Run from source: `run.bat`; isolated settings: `set LAYOUTFIXER_DATA_DIR=%TEMP%\lf-dev`

## Rules

- Tests must not send real keystrokes (SendInput), touch the real clipboard, focus/show windows, or
  call LoadKeyboardLayout (it adds a layout to the user's switcher). Real-Windows tests use the hidden
  hosts in tests/hosts/. Real clipboard tests are opt-in (LAYOUTFIXER_REAL_CLIPBOARD_TESTS=1).
- Never log user text or clipboard contents (lengths and outcomes only).
- Never select with Ctrl+A. Never paste over U+FFFC (embedded objects). Read back and verify every write.
- Conversion is strict key-for-key, 1:1 per character (length preserved; target code relies on that).
  The direction comes only from the focused window's active layout (en -> he, he -> en). The user
  explicitly rejected language detection and word/URL/punctuation heuristics - do not reintroduce them.
- Chromium applies UI Automation Select() asynchronously (~5-10 ms): always wait for the reported
  selection (UiaTarget._wait_for_selection), never check it once. Real-Chrome tests run on a hidden
  desktop (tests/hosts/hidden_desktop.py), never on the user's screen.
- Every step of a press is logged (`focus:`, `layout:`, `target:`, `read:`, ..., `FAILED at <step>`).
- The engine runs on the dispatcher's worker thread (COM/UIA objects live there); UI only on the Qt thread.
- The one-file exe runs as parent + child process: stop it with `taskkill /T`.
- Do not touch other projects in the parent folder.

## macOS port (README-macOS.md)

- Mac layer in `layoutfixer/mac/` (shortcut Cmd+Fn via a Quartz event tap, Accessibility API target,
  NSPasteboard, TIS layouts, LaunchAgent). Shared code picks it via `config.IS_MAC`; Windows behaviour
  must stay identical. PyObjC is imported lazily so `tests/test_mac_*.py` run on Windows with fakes.
- Mac key tables come from the Mac's installed layouts (UCKeyTranslate), never from the Windows table.
- TIS calls only on the main thread (`mainthread.MainThreadRunner`); AX calls on the worker thread.
- Package: `build_mac.bat` -> `dist\mac\LayoutFixer-macOS.zip`, built on Windows from pinned downloads
  (py2app stub, python-build-standalone 3.13 merged to universal, PySide6 6.9.3 - newer PySide6
  binaries need macOS 15/26). Always run `tools\verify_mac_bundle.py` after changing the build.
- Nothing has run on a real Mac yet: never claim Mac behaviour as tested; use the README-macOS checklist.
