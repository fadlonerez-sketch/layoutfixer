@echo off
rem Run Layout Fixer from source (creates .venv on first use).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  py -3 -m venv .venv || python -m venv .venv || exit /b 1
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" %*
