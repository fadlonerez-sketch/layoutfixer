"""The Mach-O tools and the bundle verifier catch what they are meant to catch.

Uses the built dist/mac/LayoutFixer-macOS.zip (skipped when it has not been built): each test
damages one thing in memory and expects tools/verify_mac_bundle.py to report it.
"""

import plistlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import macho  # noqa: E402

ZIP = ROOT / "dist" / "mac" / "LayoutFixer-macOS.zip"
pytestmark = pytest.mark.skipif(not ZIP.exists(), reason="macOS bundle not built (tools/build_mac_app.py)")

STUB = "Layout Fixer.app/Contents/MacOS/LayoutFixer"
COCOA = "Layout Fixer.app/Contents/Resources/lib/python3.13/site-packages/PySide6/Qt/plugins/platforms/libqcocoa.dylib"


@pytest.fixture(scope="module")
def checker_class():
    import verify_mac_bundle
    return verify_mac_bundle.Checker


def damaged(checker_class, name, change):
    c = checker_class(ZIP)
    real = c.read

    def read(n):
        data = real(n)
        return change(data) if n == name else data

    c.read = read
    return c


def test_fat_merge_round_trip_keeps_signatures(checker_class):
    data = checker_class(ZIP).read(STUB)
    slices = macho.parse(data)
    merged = macho.fat_merge(*(s.data for s in slices))
    again = macho.parse(merged)
    assert [s.arch for s in again] == ["x86_64", "arm64"]
    assert [s.data for s in again] == [s.data for s in slices]
    assert next(s for s in again if s.arch == "arm64").verify_signature() == ""
    with pytest.raises(ValueError):
        macho.fat_merge(slices[1].data, slices[1].data)


def test_signature_check_detects_a_changed_byte(checker_class):
    arm = next(s for s in macho.parse(checker_class(ZIP).read(STUB)) if s.arch == "arm64")
    broken = bytearray(arm.data)
    broken[0x4000 + 17] ^= 0xFF  # inside the code, past the header page
    assert "mismatch" in macho.parse(bytes(broken))[0].verify_signature()


def test_clean_bundle_passes(checker_class):
    c = checker_class(ZIP)
    info = c.layout()
    c.launcher_and_python()
    c.machos(info)
    assert c.failures == []


def test_verifier_catches_damaged_signature(checker_class):
    def flip(data):
        arm = next(s for s in macho.parse(data) if s.arch == "arm64")
        start = data.index(arm.data)
        b = bytearray(data)
        b[start + 0x4000 + 5] ^= 0xFF
        return bytes(b)

    c = damaged(checker_class, COCOA, flip)
    c.machos(c.layout())
    assert any("libqcocoa" in f and "signature" in f for f in c.failures)


def test_verifier_catches_missing_library(checker_class):
    c = checker_class(ZIP)
    real = c.exists
    c.exists = lambda n: "QtDBus.framework/Versions/A/QtDBus" not in n and real(n)
    c.machos(c.layout())
    assert any("QtDBus" in f for f in c.failures)


def test_verifier_catches_dock_icon_and_missing_python_symbols(checker_class):
    def no_uielement(data):
        info = plistlib.loads(data)
        del info["LSUIElement"]
        return plistlib.dumps(info)

    c = damaged(checker_class, "Layout Fixer.app/Contents/Info.plist", no_uielement)
    c.layout()
    assert any("LSUIElement" in f for f in c.failures)


def test_verifier_catches_unknown_pyobjc_name(checker_class):
    name = "Layout Fixer.app/Contents/Resources/app/layoutfixer/mac/keyboard.py"
    c = damaged(checker_class, name, lambda d: d.replace(b"Q.CGEventPost(", b"Q.CGEventPostTypo("))
    c.pyobjc_names()
    assert any("CGEventPostTypo" in f for f in c.failures)


def test_verifier_catches_missing_import(checker_class):
    name = "Layout Fixer.app/Contents/Resources/app/layoutfixer/mac/env.py"
    c = damaged(checker_class, name, lambda d: d.replace(b"import logging", b"import logging\nimport tkinter"))
    c.imports()
    assert any("tkinter" in f for f in c.failures)
