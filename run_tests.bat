@echo off
rem Run the automated tests. No real keystrokes are sent and the clipboard is not touched.
rem Opt-in real clipboard round trip:  set LAYOUTFIXER_REAL_CLIPBOARD_TESTS=1
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest %*
