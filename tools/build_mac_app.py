"""Build "Layout Fixer.app" for macOS 12+ (Apple silicon and Intel) on any OS, zipped for sending.

    build\\venv313\\Scripts\\python tools\\build_mac_app.py     (or build_mac.bat, which also runs the tests)

Run it with Python 3.13 (the version inside the app) so it can precompile the .pyc files.
Nothing is compiled from source; the app is assembled from pinned, hash-checked downloads:

* the prebuilt universal launcher of py2app 0.28.10 (MIT). It loads Python into the app's own
  process, so macOS treats the running app as "Layout Fixer" - its entry in the Accessibility
  list, its menu-bar-only mode (LSUIElement) and its icon - not as a "python" process;
* CPython 3.13 from python-build-standalone for arm64 and x86_64, merged into universal
  binaries by tools/macho.fat_merge (slices copied byte for byte, so their signatures stay valid);
* the universal2 wheels of requirements-mac.txt, trimmed to the Qt modules the app uses;
* this repository's layoutfixer package and packaging/mac/__boot__.py.

Output: dist/mac/LayoutFixer-macOS.zip ("Layout Fixer.app" + "Read Me First.txt"); check it with
tools/verify_mac_bundle.py.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import posixpath
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import macho  # noqa: E402

CACHE = ROOT / "build" / "mac-cache"
OUT = ROOT / "dist" / "mac" / "LayoutFixer-macOS.zip"
APP = "Layout Fixer.app"
BUNDLE_ID = "local.layoutfixer.LayoutFixer"
MIN_MACOS = "12.0"
PY = "3.13"
PBS_TAG = "20261026"
PYTHONS = {  # python-build-standalone (sha256 from the release's SHA256SUMS)
    "arm64": ("cpython-3.13.18+20261026-aarch64-apple-darwin-install_only_stripped.tar.gz",
              "8392b6ea51d94391befb2c31ebe75463f045d0b69dfcf5e1bb3234e1f5fa3405"),
    "x86_64": ("cpython-3.13.18+20261026-x86_64-apple-darwin-install_only_stripped.tar.gz",
               "7412c19d896c99431b74a18a5643e110449a7f9590fbab179c3e5ab27b9aa9e3"),
}
PY2APP = ("py2app-0.28.10.tar.gz",
          "https://files.pythonhosted.org/packages/93/82/79a2aaaf86c44c6018edce1a028cf821acec4c3ca63e2b5781f16822c99f/"
          "py2app-0.28.10.tar.gz",
          "fd38f4a0083d4d1e91ea336eaef678b99d9e1b95ac6302315cad22fa5e859cb1")
STUB = "py2app-0.28.10/py2app/apptemplate/prebuilt/main-universal2"
ZIP_DATE = (2026, 10, 28, 0, 0, 0)

C = f"{APP}/Contents"
RES = f"{C}/Resources"
STDLIB = f"{RES}/lib/python{PY}"
SITE = f"{STDLIB}/site-packages"

DROP_STDLIB = ("test/", "idlelib/", "tkinter/", "turtledemo/", "ensurepip/", "lib2to3/", "site-packages/",
               f"config-{PY}-darwin/", "pydoc_data/", "lib-dynload/_tkinter", "turtle.py", "__phello__/")
QT_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtNetwork")
QT_PLUGINS = ("platforms/libqcocoa.dylib", "platforms/libqoffscreen.dylib", "platforms/libqminimal.dylib",
              "styles/libqmacstyle.dylib")


@dataclass
class Entry:
    data: bytes
    mode: int = 0o644


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- downloads
def fetch(name: str, url: str, sha256: str, folder: str) -> Path:
    path = CACHE / folder / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        log(f"  downloading {name}")
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read()
        path.write_bytes(data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        raise SystemExit(f"checksum mismatch for {name}: {digest}")
    return path


def fetch_wheels() -> list[Path]:
    folder = CACHE / "wheels"
    subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--require-hashes",
                    "--only-binary=:all:", "--platform", "macosx_12_0_universal2", "--python-version", PY,
                    "--implementation", "cp", "-d", str(folder), "-r", str(ROOT / "requirements-mac.txt")],
                   check=True)
    wanted = [line.split("==") for line in (ROOT / "requirements-mac.txt").read_text().splitlines()
              if "==" in line]
    out = []
    for name, version in wanted:
        version = version.split()[0]
        norm = name.replace("-", "_").lower()
        match = [p for p in folder.glob("*.whl") if p.name.lower().startswith(f"{norm}-{version}-")]
        if len(match) != 1:
            raise SystemExit(f"wheel for {name}=={version} not found in {folder}")
        out.append(match[0])
    return out


# ---------------------------------------------------------------- python
def read_python(tar_path: Path) -> dict[str, bytes]:
    """Files of the standalone Python we keep, keyed by their path under python/."""
    files: dict[str, bytes] = {}
    with tarfile.open(tar_path) as t:
        for m in t.getmembers():
            if not m.isfile() or not m.name.startswith("python/"):
                continue
            rel = m.name[len("python/"):]
            if rel == f"lib/libpython{PY}.dylib" or rel == f"lib/python{PY}/LICENSE.txt":
                pass
            elif rel.startswith(f"lib/python{PY}/"):
                sub = rel[len(f"lib/python{PY}/"):]
                if sub.startswith(DROP_STDLIB) or "/__pycache__/" in f"/{sub}" or sub.endswith(".pyc"):
                    continue
            else:
                continue
            files[rel] = t.extractfile(m).read()
    return files


def universal_python(tree: dict[str, Entry], report: dict) -> bytes:
    arm = read_python(fetch(PYTHONS["arm64"][0], _pbs_url(PYTHONS["arm64"][0]), PYTHONS["arm64"][1], "python"))
    x86 = read_python(fetch(PYTHONS["x86_64"][0], _pbs_url(PYTHONS["x86_64"][0]), PYTHONS["x86_64"][1], "python"))
    if set(arm) != set(x86):
        raise SystemExit(f"the two Python builds differ in files: {sorted(set(arm) ^ set(x86))[:10]}")
    differing, merged = [], 0
    for rel in sorted(arm):
        a, b = arm[rel], x86[rel]
        if macho.is_macho(a):
            data = macho.fat_merge(a, b)
            if sorted(s.arch for s in macho.parse(data)) != ["arm64", "x86_64"]:
                raise SystemExit(f"unexpected architectures in {rel}")
            mode = 0o755
            merged += 1
        else:
            data, mode = a, 0o644
            if a != b:
                differing.append(rel)  # e.g. _sysconfigdata (compiler flags): the arm64 copy is kept
        if rel == f"lib/libpython{PY}.dylib":
            tree[f"{C}/Frameworks/libpython{PY}.dylib"] = Entry(data, mode)
        elif rel == f"lib/python{PY}/LICENSE.txt":
            tree[f"{RES}/LICENSES/Python-LICENSE.txt"] = Entry(data)
            tree[f"{STDLIB}/LICENSE.txt"] = Entry(data)
        else:
            tree[f"{RES}/{rel}"] = Entry(data, mode)
    report["python_universal_binaries"] = merged
    report["python_files_differing_between_architectures"] = differing
    return arm[f"lib/libpython{PY}.dylib"]


def _pbs_url(name: str) -> str:
    return (f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"
            + name.replace("+", "%2B"))


# ---------------------------------------------------------------- wheels
def wheel_files(path: Path) -> dict[str, Entry]:
    out: dict[str, Entry] = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            first, _, rest = name.partition("/")
            if first.endswith(".data"):
                kind, _, rest2 = rest.partition("/")
                if kind not in ("purelib", "platlib"):
                    continue
                name = rest2
            if name.startswith("PyObjCTest/") or ".dSYM/" in name:
                continue  # pyobjc-core's own test suite and debug symbols
            if "__pycache__/" in name or name.endswith(".pyc"):
                continue  # stale bytecode of other Python versions; precompile() writes ours
            data = z.read(info)
            mode = 0o755 if macho.is_macho(data) else 0o644
            out[name] = Entry(data, mode)
    return out


def trim_pyside(files: dict[str, Entry], others: dict[str, Entry], report: dict) -> dict[str, Entry]:
    """Keep the Qt modules the app imports, the Qt plugins it needs, and every library they load."""
    pool = {**files, **others}
    roots = [f"PySide6/{m}.abi3.so" for m in QT_MODULES] + [f"PySide6/Qt/plugins/{p}" for p in QT_PLUGINS]
    keep_bins: set[str] = set()
    todo = list(roots)
    while todo:
        path = todo.pop()
        if path in keep_bins:
            continue
        if path not in pool:
            raise SystemExit(f"missing in the wheels: {path}")
        keep_bins.add(path)
        for sl in macho.parse(pool[path].data):
            for kind, dep in sl.dylibs:
                if dep.startswith(("/System/", "/usr/lib/")):
                    continue
                cands = macho.resolve(dep, path, f"{C}/MacOS/LayoutFixer", sl.rpaths)
                hit = next((c for c in cands if c in pool), None)
                if hit is None:
                    if kind == "weak":
                        continue
                    raise SystemExit(f"{path} needs {dep}, not found in the wheels")
                todo.append(hit)
    frameworks = {p.split(".framework/")[0] + ".framework/" for p in keep_bins if ".framework/" in p}
    kept = {}
    for name, e in files.items():
        if name in keep_bins or any(name.startswith(f) for f in frameworks):
            kept[name] = e
        elif macho.is_macho(e.data):
            continue
        elif name.startswith("PySide6/Qt/"):
            continue  # qml, translations, metatypes, plugins not listed...
        elif name.endswith(".pyi") or name.startswith(("PySide6/include/", "PySide6/typesystems/",
                                                         "PySide6/glue/", "PySide6/scripts/", "PySide6/doc/")):
            continue
        elif ".app/" in name:
            continue  # Designer.app, Linguist.app, Assistant.app
        else:
            kept[name] = e
    report["qt_frameworks"] = sorted(f.rsplit("/", 2)[-2] for f in frameworks)
    report["qt_binaries_kept"] = len(keep_bins)
    return kept


# ---------------------------------------------------------------- app files
def app_files(tree: dict[str, Entry]) -> None:
    for path in sorted((ROOT / "layoutfixer").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree[f"{RES}/app/{rel}"] = Entry(path.read_bytes())
    tree[f"{RES}/__boot__.py"] = Entry((ROOT / "packaging" / "mac" / "__boot__.py").read_bytes())


def precompile(tree: dict[str, Entry], report: dict) -> None:
    """__pycache__/*.cpython-313.pyc next to every module (unchecked-hash: valid whatever the file dates)."""
    if sys.version_info[:2] != tuple(int(x) for x in PY.split(".")):
        log(f"  WARNING: running Python {sys.version_info[0]}.{sys.version_info[1]}, not {PY}: no .pyc files "
            "(the app still works, it starts slower)")
        report["pyc"] = 0
        return
    from importlib._bootstrap_external import _code_to_hash_pyc
    tag = sys.implementation.cache_tag
    made, failed = 0, []
    for path in [p for p in tree if p.endswith(".py") and p.startswith(f"{RES}/")]:
        if path == f"{RES}/__boot__.py":
            continue  # run from source by the launcher
        source = tree[path].data
        try:
            code = compile(source, "/" + path, "exec", dont_inherit=True)
        except SyntaxError:
            failed.append(path)
            continue
        folder, name = posixpath.split(path)
        pyc = f"{folder}/__pycache__/{name[:-3]}.{tag}.pyc"
        tree[pyc] = Entry(bytes(_code_to_hash_pyc(code, importlib.util.source_hash(source), checked=False)))
        made += 1
    report["pyc"] = made
    report["pyc_failed"] = failed


def icns() -> bytes:
    """The app icon (layoutfixer/ui/icon.py) as a .icns file of PNG images."""
    os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QGuiApplication

    from layoutfixer.ui.icon import render
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - no window is shown

    def png(size: int) -> bytes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        render(size).save(buf, "PNG")
        return bytes(ba.data())

    chunks = b""
    for ostype, size in (("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512),
                         ("ic10", 1024), ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512)):
        data = png(size)
        chunks += ostype.encode() + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks


def info_plist(version: str) -> bytes:
    return plistlib.dumps({
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "Layout Fixer",
        "CFBundleName": "Layout Fixer",
        "CFBundleExecutable": "LayoutFixer",
        "CFBundleIconFile": "LayoutFixer",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "????",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSUIElement": True,                       # menu-bar app: no Dock icon
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Layout Fixer - Hebrew/English wrong-layout fixer",
        # Read by the launcher (py2app's stub):
        "PyRuntimeLocations": [f"@executable_path/../Frameworks/libpython{PY}.dylib"],
        "PyMainFileNames": ["__boot__"],
        "PyResourcePackages": [],
        "PyOptions": {"use_pythonpath": False},
    })


AUX_PYTHON = b"""#!/bin/sh
# Required by the app's launcher (it marks the bundle's Python home); Layout Fixer never runs it.
echo "This file is part of Layout Fixer.app and is not meant to be run." >&2
exit 1
"""


def notices(versions: dict) -> bytes:
    lines = [
        "Layout Fixer for macOS - third-party components",
        "",
        f"Python {versions['python']} (python-build-standalone {PBS_TAG}) - PSF License: LICENSES/Python-LICENSE.txt",
        "py2app 0.28.10 launcher stub (Contents/MacOS/LayoutFixer) - MIT: LICENSES/py2app-LICENSE.txt",
    ]
    for name, version in versions["wheels"]:
        lines.append(f"{name} {version} - license in lib/python{PY}/site-packages/*{name.replace('-', '_')}*.dist-info")
    lines += [
        "",
        "Qt (inside PySide6) is used under the GNU LGPL v3. The Qt libraries are the unmodified, dynamically",
        "linked copies from the PySide6-Essentials wheel (site-packages/PySide6/Qt/lib) and can be replaced",
        "by compatible builds. Qt source code: https://download.qt.io/official_releases/qt/",
    ]
    return ("\n".join(lines) + "\n").encode()


# ---------------------------------------------------------------- zip
def write_zip(tree: dict[str, Entry], extra: dict[str, bytes], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    dirs = set()
    for path in list(tree) + [f"{C}/Frameworks/x"]:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d in sorted(dirs):
            zi = zipfile.ZipInfo(d + "/", ZIP_DATE)
            zi.create_system = 3
            zi.external_attr = (0o040755 << 16) | 0x10
            z.writestr(zi, b"")
        for path in sorted(tree):
            e = tree[path]
            zi = zipfile.ZipInfo(path, ZIP_DATE)
            zi.create_system = 3
            zi.external_attr = (0o100000 | e.mode) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, e.data)
        for name, data in extra.items():
            zi = zipfile.ZipInfo(name, ZIP_DATE)
            zi.create_system = 3
            zi.external_attr = 0o100644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    os.replace(tmp, out)


def main() -> int:
    from layoutfixer import __version__
    report: dict = {"version": __version__}
    tree: dict[str, Entry] = {}

    log("[1/6] Python (arm64 + x86_64 -> universal)")
    universal_python(tree, report)

    log("[2/6] Wheels")
    wheels = fetch_wheels()
    pyside = shiboken = None
    site: dict[str, Entry] = {}
    versions = []
    for w in wheels:
        name, version = w.name.split("-")[:2]
        versions.append((name, version))
        files = wheel_files(w)
        if name.lower().startswith("pyside6"):
            pyside = files
        elif name.lower() == "shiboken6":
            shiboken = files
            site.update(files)
        else:
            site.update(files)
    assert pyside is not None and shiboken is not None
    site.update(trim_pyside(pyside, shiboken, report))
    for name, e in site.items():
        tree[f"{SITE}/{name}"] = e

    log("[3/6] Launcher, app, resources")
    sdist = fetch(PY2APP[0], PY2APP[1], PY2APP[2], "py2app")
    with tarfile.open(sdist) as t:
        stub = t.extractfile(STUB).read()
        tree[f"{RES}/LICENSES/py2app-LICENSE.txt"] = Entry(t.extractfile("py2app-0.28.10/LICENSE.txt").read())
    tree[f"{C}/MacOS/LayoutFixer"] = Entry(stub, 0o755)
    tree[f"{C}/MacOS/python"] = Entry(AUX_PYTHON, 0o755)
    tree[f"{C}/Info.plist"] = Entry(info_plist(__version__))
    tree[f"{C}/PkgInfo"] = Entry(b"APPL????")
    tree[f"{RES}/LayoutFixer.icns"] = Entry(icns())
    tree[f"{RES}/THIRD_PARTY_NOTICES.txt"] = Entry(notices({"python": PYTHONS["arm64"][0].split("-")[1],
                                                             "wheels": versions}))
    app_files(tree)

    log("[4/6] Precompiling .pyc")
    precompile(tree, report)

    log("[5/6] Writing the zip")
    readme = (ROOT / "packaging" / "mac" / "Read Me First.txt").read_bytes()
    write_zip(tree, {"Read Me First.txt": readme}, OUT)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    (OUT.parent / (OUT.name + ".sha256")).write_text(f"{digest}  {OUT.name}\n")

    log("[6/6] Done")
    report["files"] = len(tree)
    report["unpacked_mb"] = round(sum(len(e.data) for e in tree.values()) / 1e6, 1)
    report["zip_mb"] = round(OUT.stat().st_size / 1e6, 1)
    report["zip_sha256"] = digest
    report["wheels"] = versions
    (OUT.parent / "build-report.json").write_text(json.dumps(report, indent=2))
    log(json.dumps({k: v for k, v in report.items() if k != "pyc_failed"}, indent=2))
    log(f"Output: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
