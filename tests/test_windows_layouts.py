"""REAL WINDOWS: compare the built-in table with the US / Hebrew layouts installed on this PC.

Reads key tables with ToUnicodeEx only (no input, no layout loading, no switching).
"""

import pytest

from layoutfixer.keymap import KEYS
from layoutfixer.win import layouts

INSTALLED = layouts.installed_layouts()
HE = [h for h in INSTALLED if layouts.lang_of(h) == "he"]
US = [h for h in INSTALLED if h & 0xFFFF == 0x0409]


def test_both_languages_installed_here():
    """Environment check for the real-Windows tests below (and for layout switching)."""
    assert HE, "no Hebrew keyboard layout installed"
    assert US, "no US English keyboard layout installed"


@pytest.mark.skipif(not US, reason="US layout not installed")
@pytest.mark.parametrize("hkl", US, ids=hex)
def test_us_table_matches_windows(hkl):
    table = layouts.key_table(hkl)
    for sc, us, us_sh, _he, _he_sh in KEYS:
        assert table[sc] == (us, us_sh), f"scan code {sc:#04x}"


@pytest.mark.skipif(not HE, reason="Hebrew layout not installed")
@pytest.mark.parametrize("hkl", HE, ids=hex)
def test_hebrew_table_matches_windows(hkl):
    table = layouts.key_table(hkl)
    for sc, _us, _us_sh, he, he_sh in KEYS:
        assert table[sc] == (he, he_sh), f"scan code {sc:#04x}"


def test_lang_of():
    assert layouts.lang_of(0x04090409) == "en"
    assert layouts.lang_of(0x0809_0809) == "en"  # English (UK)
    assert layouts.lang_of(0xFFFFFFFFF03D040D) == "he"  # Hebrew (Standard)
    assert layouts.lang_of(0x0407_0407) is None  # German


def test_find_layout_prefers_us_and_hebrew_israel():
    lst = [0x08090809, 0x04090409, 0xF03D040D]
    assert layouts.find_layout("en", lst) == 0x04090409
    assert layouts.find_layout("he", lst) == 0xF03D040D
    assert layouts.find_layout("en", [0x08090809]) == 0x08090809
    assert layouts.find_layout("he", [0x04090409]) is None
