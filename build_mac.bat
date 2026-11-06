@echo off
rem Build dist\mac\LayoutFixer-macOS.zip: "Layout Fixer.app" for macOS 12+ (Apple silicon + Intel).
rem   1. creates build\venv313 (Python 3.13, the version inside the app) if needed
rem   2. runs the test suite with it
rem   3. assembles the app (tools\build_mac_app.py) and checks it (tools\verify_mac_bundle.py)
rem See README-macOS.md.
setlocal
cd /d "%~dp0"
set PY=build\venv313\Scripts\python.exe
if not exist "%PY%" (
  py -3 tools\setup_mac_build_env.py || python tools\setup_mac_build_env.py || goto :error
)

echo [1/3] Tests (Python 3.13)...
"%PY%" -m pytest -q -p no:cacheprovider || goto :error

echo [2/3] Building the app...
"%PY%" tools\build_mac_app.py || goto :error

echo [3/3] Checking dist\mac\LayoutFixer-macOS.zip...
"%PY%" tools\verify_mac_bundle.py || goto :error
echo.
echo Done: dist\mac\LayoutFixer-macOS.zip
exit /b 0

:error
echo BUILD FAILED
exit /b 1
