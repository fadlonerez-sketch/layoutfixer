@echo off
rem Build dist\LayoutFixer.exe (single file, no console) and verify it.
rem   1. creates .venv if needed and installs requirements-dev.txt
rem   2. runs the test suite
rem   3. generates the UI Automation wrapper + icon, runs PyInstaller
rem   4. runs tools\verify_build.py (exe self-test + tray start-up check)
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  py -3 -m venv .venv || python -m venv .venv || goto :error
)
"%PY%" -m pip install -q -r requirements-dev.txt || goto :error

echo [1/4] Tests...
"%PY%" -m pytest -q || goto :error

echo [2/4] UI Automation wrapper and icon...
"%PY%" -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')" || goto :error
"%PY%" tools\make_icon.py || goto :error

echo [3/4] PyInstaller...
if exist "dist\LayoutFixer.exe" del /q "dist\LayoutFixer.exe"
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN layoutfixer.spec || goto :error

echo [4/4] Verifying dist\LayoutFixer.exe...
"%PY%" tools\verify_build.py
if "%ERRORLEVEL%"=="3" goto :blocked
if not "%ERRORLEVEL%"=="0" goto :error
echo.
echo Done: dist\LayoutFixer.exe
exit /b 0

:blocked
echo Windows application control (e.g. Smart App Control) blocked the new exe on this PC.
echo Run from source instead: run.bat
exit /b 3
:error
echo BUILD FAILED
exit /b 1
