"""Check dist/mac/LayoutFixer-macOS.zip without a Mac: everything that can be checked from the files.

    build\\venv313\\Scripts\\python tools\\verify_mac_bundle.py [zip]

Checks: bundle layout and Info.plist; the launcher's requirements (PyRuntimeLocations, the Python
symbols it looks up, PYTHONHOME layout, __boot__.py); every Mach-O file is universal (arm64 +
x86_64), has a valid code signature in its arm64 slice (Apple silicon refuses unsigned code), needs
at most the declared minimum macOS, and finds every library it links; Unix permissions survive in
the zip; the C modules the app imports are built into libpython; every module the app imports
on a Mac is present; every PyObjC function / constant the Mac code uses exists in the bundled
PyObjC; the .py files compile and the .pyc files match this Python version.

What it cannot check: that macOS runs it - that needs a Mac (see README-macOS.md).
Exit code 0 = all checks passed.
"""

from __future__ import annotations

import ast
import importlib.util
import plistlib
import re
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import macho  # noqa: E402

APP = "Layout Fixer.app"
C = f"{APP}/Contents"
RES = f"{C}/Resources"
PY = "3.13"
STDLIB = f"{RES}/lib/python{PY}"
SITE = f"{STDLIB}/site-packages"
SYSTEM_PREFIXES = ("/System/Library/", "/usr/lib/")
STUB_SYMBOLS = ("Py_SetProgramName", "Py_Initialize", "PyRun_SimpleFile", "Py_Finalize", "PySys_GetObject",
                "PySys_SetArgv", "PyObject_GetAttrString", "Py_BuildValue", "PySys_SetObject", "Py_DecodeLocale",
                "PyBytes_FromString")
# C modules imported (directly or by the stdlib modules the app uses); python-build-standalone builds
# them into libpython, so each needs a PyInit_<name> there or a .so in lib-dynload.
C_MODULES = ("_ctypes", "pyexpat", "_posixsubprocess", "select", "fcntl", "zlib", "_struct", "math", "_datetime",
             "_json", "binascii", "_random", "_bisect", "_heapq", "_queue", "unicodedata", "_opcode",
             "_contextvars", "_sha2", "_blake2", "_hashlib", "_socket", "array", "_pickle", "_lzma", "_bz2",
             "termios", "_scproxy", "grp", "_md5", "_sha1", "_sha3", "_statistics", "mmap", "_asyncio",
             "_signal", "posix", "_io", "_thread", "atexit", "time", "itertools", "_functools", "_collections",
             "_abc", "_sre", "_codecs", "_weakref", "_locale", "errno", "_stat", "faulthandler")
# Modules of the app that run on a Mac (the Windows-only ones - win/, win_env, uia, targets/native_edit,
# targets/uia_target, startup, selftest - are never imported there).
MAC_MODULES = ("__init__", "__main__", "app", "clipboard", "config", "converter", "engine", "env_types", "hotkeys",
               "keymap", "mainthread", "paste", "textindex", "targets/__init__", "targets/base",
               "targets/clipboard_target", "ui/__init__", "ui/icon", "ui/settings_window", "ui/toast",
               "mac/__init__", "mac/ax", "mac/ax_target", "mac/clipboard", "mac/env", "mac/hotkeys",
               "mac/keyboard", "mac/keycodes", "mac/keymap_mac", "mac/layouts", "mac/permissions",
               "mac/selftest", "mac/startup", "mac/tis", "mac/ui")
# Where the names used through each PyObjC module are defined.
PYOBJC_SOURCES = {"Q": ("Quartz/", "CoreFoundation/"), "Quartz": ("Quartz/", "CoreFoundation/"),
                  "AS": ("HIServices/", "ApplicationServices/", "CoreFoundation/"),
                  "AppKit": ("AppKit/",), "Foundation": ("Foundation/",), "CoreFoundation": ("CoreFoundation/",),
                  "ApplicationServices": ("HIServices/", "ApplicationServices/")}


class Checker:
    def __init__(self, path: Path):
        self.zip = zipfile.ZipFile(path)
        self.infos = {i.filename: i for i in self.zip.infolist()}
        self.failures: list[str] = []
        self.notes: list[str] = []
        self.count = 0

    def read(self, name: str) -> bytes:
        return self.zip.read(self.infos[name])

    def exists(self, name: str) -> bool:
        return name in self.infos

    def check(self, ok: bool, what: str) -> bool:
        self.count += 1
        if not ok:
            self.failures.append(what)
        return ok

    def mode(self, name: str) -> int:
        return (self.infos[name].external_attr >> 16) & 0xFFFF

    # ------------------------------------------------------------------ checks
    def layout(self) -> dict:
        tops = {n.split("/")[0] for n in self.infos}
        self.check(tops == {APP, "Read Me First.txt"}, f"zip top level is {sorted(tops)}")
        info = plistlib.loads(self.read(f"{C}/Info.plist"))
        for key in ("CFBundleExecutable", "CFBundleIdentifier", "CFBundleName", "CFBundleIconFile",
                    "LSMinimumSystemVersion", "PyRuntimeLocations", "PyMainFileNames"):
            self.check(key in info, f"Info.plist lacks {key}")
        self.check(info.get("LSUIElement") is True, "LSUIElement is not true (the app would show in the Dock)")
        exe = f"{C}/MacOS/{info['CFBundleExecutable']}"
        self.check(self.exists(exe) and self.mode(exe) & 0o111 != 0, f"{exe} missing or not executable")
        aux = f"{C}/MacOS/python"
        self.check(self.exists(aux) and stat.S_ISREG(self.mode(aux)),
                   "Contents/MacOS/python must be a regular file (the launcher sets PYTHONHOME only then)")
        self.check(self.exists(f"{RES}/{info['CFBundleIconFile']}.icns")
                   and self.read(f"{RES}/{info['CFBundleIconFile']}.icns")[:4] == b"icns", "icon missing or invalid")
        for loc in info["PyRuntimeLocations"]:
            rel = loc.replace("@executable_path/../", f"{C}/")
            self.check(self.exists(rel), f"PyRuntimeLocations entry {loc} -> {rel} not in the bundle")
        self.check(self.exists(f"{RES}/{info['PyMainFileNames'][0]}.py"), "__boot__.py missing")
        self.check(self.exists(f"{STDLIB}/os.py") and self.exists(f"{STDLIB}/encodings/__init__.py"),
                   "standard library not at Resources/lib/python3.13 (PYTHONHOME layout)")
        self.check(self.exists(f"{C}/Frameworks/"), "Contents/Frameworks folder missing")
        self.check(self.mode("Read Me First.txt") & 0o444 == 0o444, "Read Me First.txt not readable")
        return info

    def machos(self, info: dict) -> None:
        minimum = tuple(int(x) for x in info["LSMinimumSystemVersion"].split("."))
        exe = f"{C}/MacOS/{info['CFBundleExecutable']}"
        found = 0
        for name, zi in self.infos.items():
            if name.endswith("/") or zi.file_size < 4096 and not name.startswith(f"{C}/MacOS/"):
                continue
            data = self.read(name)
            if not macho.is_macho(data):
                continue
            found += 1
            self.check(self.mode(name) & 0o111 != 0, f"{name}: not executable in the zip")
            slices = macho.parse(data)
            archs = sorted(s.arch for s in slices)
            self.check(archs == ["arm64", "x86_64"], f"{name}: architectures {archs}, not universal")
            for s in slices:
                if s.arch == "arm64":
                    problem = s.verify_signature()
                    self.check(problem == "", f"{name} (arm64): code signature {problem}")
                if s.minos:
                    v = tuple(int(x) for x in s.minos.split("."))
                    self.check(v <= minimum, f"{name} ({s.arch}): built for macOS {s.minos}, "
                                             f"newer than LSMinimumSystemVersion {info['LSMinimumSystemVersion']}")
                for kind, dep in s.dylibs:
                    if dep.startswith(SYSTEM_PREFIXES):
                        continue
                    self.check("Python.framework" not in dep and "libpython" not in dep,
                               f"{name}: links a Python library itself ({dep})")
                    cands = macho.resolve(dep, name, exe, s.rpaths)
                    if not any(self.exists(c) for c in cands) and kind != "weak":
                        self.check(False, f"{name} ({s.arch}): {dep} not found (looked at {cands})")
        self.check(found > 10, f"only {found} Mach-O files found")
        self.notes.append(f"{found} Mach-O files: all universal, arm64 signatures verified, dependencies resolved")

    def launcher_and_python(self) -> None:
        lib = self.read(f"{C}/Frameworks/libpython{PY}.dylib")
        for s in macho.parse(lib):
            syms = s.exported_symbols()
            missing = [n for n in STUB_SYMBOLS if "_" + n not in syms]
            self.check(not missing, f"libpython ({s.arch}) lacks what the launcher looks up: {missing}")
            dynload = {n.rsplit("/", 1)[-1].split(".")[0] for n in self.infos if "/lib-dynload/" in n}
            absent = [m for m in C_MODULES if "_PyInit_" + m not in syms and m not in dynload]
            self.check(not absent, f"C modules missing from libpython ({s.arch}): {absent}")
        stub = macho.parse(self.read(f"{C}/MacOS/LayoutFixer"))
        self.check(all(s.filetype == "execute" for s in stub), "launcher is not an executable")

    def python_sources(self) -> None:
        magic = importlib.util.MAGIC_NUMBER
        compiled = 0
        for name in self.infos:
            if name.endswith(".pyc"):
                head = self.read(name)[:8]
                ok = head[:4] == magic and int.from_bytes(head[4:8], "little") == 0b01
                self.check(ok, f"{name}: not an unchecked-hash .pyc of Python {PY}")
            elif name.startswith(f"{RES}/app/") and name.endswith(".py") or name == f"{RES}/__boot__.py":
                try:
                    compile(self.read(name), name, "exec", dont_inherit=True)
                    compiled += 1
                except SyntaxError as e:
                    self.check(False, f"{name}: {e}")
        self.notes.append(f"{compiled} app sources compile with Python {sys.version.split()[0]}")

    def imports(self) -> None:
        """Every module imported by the Mac code path resolves inside the bundle."""
        libsyms = macho.parse(self.read(f"{C}/Frameworks/libpython{PY}.dylib"))[0].exported_symbols()
        builtin = {s[len("_PyInit_"):] for s in libsyms if s.startswith("_PyInit_")}

        def present(mod: str) -> bool:
            top = mod.split(".")[0]
            if top in builtin or top in sys.builtin_module_names and top not in ("winreg", "msvcrt", "_winapi",
                                                                                  "nt", "_overlapped"):
                return True
            path = mod.replace(".", "/")
            for base in (f"{RES}/app", STDLIB, SITE):
                if self.exists(f"{base}/{path}.py") or self.exists(f"{base}/{path}/__init__.py"):
                    return True
                if any(n.startswith(f"{base}/{path}.") and n.endswith(".so") for n in self.infos):
                    return True
            return False

        missing = []
        for mod in MAC_MODULES:
            name = f"{RES}/app/layoutfixer/{mod}.py"
            if not self.check(self.exists(name), f"{name} missing"):
                continue
            # the package a relative import starts from
            package = ["layoutfixer"] + mod.split("/")[:-1]
            tree = ast.parse(self.read(name))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = ".".join(package[:len(package) - (node.level - 1)])
                        targets = [f"{base}.{node.module}" if node.module else base]
                    else:
                        targets = [node.module]
                else:
                    continue
                for t in targets:
                    if t.startswith(("layoutfixer.win", "layoutfixer.uia", "layoutfixer.win_env",
                                     "layoutfixer.selftest", "layoutfixer.startup")):
                        continue  # Windows-only, behind IS_MAC checks
                    if t in ("winreg", "comtypes", "comtypes.client") or t.startswith("comtypes"):
                        continue
                    if not present(t):
                        missing.append(f"{mod}: {t}")
        self.check(not missing, f"imports not found in the bundle: {sorted(set(missing))}")
        for qt in ("QtCore", "QtGui", "QtWidgets", "QtNetwork"):
            self.check(self.exists(f"{SITE}/PySide6/{qt}.abi3.so"), f"PySide6.{qt} missing")
        self.check(self.exists(f"{SITE}/PySide6/Qt/plugins/platforms/libqcocoa.dylib"), "Qt cocoa plugin missing")

    def pyobjc_names(self) -> None:
        """Each PyObjC function/constant the Mac code uses is defined in the bundled PyObjC."""
        corpus: dict[str, str] = {}
        for name in self.infos:
            if name.startswith(SITE + "/") and (name.endswith(".py") or name.endswith(".so")):
                rel = name[len(SITE) + 1:]
                corpus[rel] = self.read(name).decode("latin-1")
        used: dict[str, set[str]] = {}
        for mod in MAC_MODULES:
            if not mod.startswith("mac/") and mod not in ("app",):
                continue
            src = self.read(f"{RES}/app/layoutfixer/{mod}.py").decode()
            for alias, name in re.findall(r"\b(Q|Quartz|AS)\.([A-Za-z_]\w*)", src):
                used.setdefault(alias, set()).add(name)
            for module, names in re.findall(r"from (AppKit|Foundation|CoreFoundation|Quartz|ApplicationServices) "
                                            r"import ([\w, ]+)", src):
                used.setdefault(module, set()).update(n.strip() for n in names.split(","))
        missing, checked = [], 0
        for alias, names in used.items():
            texts = [t for rel, t in corpus.items() if rel.startswith(PYOBJC_SOURCES[alias])]
            for n in sorted(names):
                checked += 1
                if not any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", t) for t in texts):
                    missing.append(f"{alias}.{n}")
        self.check(not missing, f"PyObjC names not found: {missing}")
        self.notes.append(f"{checked} PyObjC names used by the Mac code exist in the bundled PyObjC")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "mac" / "LayoutFixer-macOS.zip"
    if sys.version_info[:2] != (3, 13):
        print(f"note: run with Python {PY} to check the .pyc files against the bundled version")
    c = Checker(path)
    info = c.layout()
    c.launcher_and_python()
    c.machos(info)
    c.python_sources()
    c.imports()
    c.pyobjc_names()
    for n in c.notes:
        print("  " + n)
    print(f"{c.count} checks, {len(c.failures)} failed")
    for f in c.failures[:60]:
        print("  FAIL " + f)
    return 1 if c.failures else 0


if __name__ == "__main__":
    sys.exit(main())
