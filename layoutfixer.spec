# PyInstaller spec: single-file, windowed LayoutFixer.exe. Build with build_exe.bat.
from pathlib import Path

ROOT = Path(SPECPATH)

excludes = [
    "tkinter", "unittest", "pydoc_data", "test", "lib2to3", "pytest", "_pytest", "pytestqt",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtMultimedia", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtConcurrent", "PySide6.QtDBus",
    "PySide6.QtHelp", "PySide6.QtPrintSupport", "PySide6.QtXml", "PySide6.QtUiTools", "PySide6.QtSvg",
    "PySide6.QtPdf", "PySide6.QtDesigner", "ssl", "_ssl",
]

# comtypes wrappers for UIAutomationCore, generated into the build venv by build_exe.bat.
hiddenimports = [
    "comtypes.gen.UIAutomationClient",
    "comtypes.gen._944DE083_8FB8_45CF_BCB7_C477ACB2F897_0_1_0",
    "comtypes.gen.stdole",
    "comtypes.gen._00020430_0000_0000_C000_000000000046_0_2_0",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
UNUSED = ("opengl32sw.dll", "/translations/", "/plugins/tls/", "/plugins/networkinformation/",
          "/plugins/imageformats/qpdf", "/plugins/imageformats/qsvg", "qt6pdf", "qt6svg", "qt6quick", "qt6qml",
          "qt6opengl", "qt6virtualkeyboard")


def keep(entry) -> bool:
    dest = "/" + entry[0].replace("\\", "/").lower()
    return not any(u in dest for u in UNUSED)


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LayoutFixer",
    icon=str(ROOT / "assets" / "layoutfixer.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    upx=False,
    runtime_tmpdir=None,
    disable_windowed_traceback=False,
)
