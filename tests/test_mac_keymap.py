"""macOS key tables and layout choice (pure logic; runs on any OS)."""

from layoutfixer.converter import Direction, convert
from layoutfixer.mac.keycodes import ISO_KEYCODES, LAYOUT_KEYCODES
from layoutfixer.mac.keymap_mac import BUILTIN_EN_TO_HE, BUILTIN_HE_TO_EN, BUILTIN_ROWS, build_tables
from layoutfixer.mac.layouts import choose_pair, pick_layout, rows_for, tables_for
from layoutfixer.mac.tis import SourceInfo

from mac_fakes import LAYOUTS, source

MAC = (BUILTIN_EN_TO_HE, BUILTIN_HE_TO_EN)


def test_spec_example_on_mac_hebrew():
    assert convert("akuo' nv eurv?", Direction.EN_TO_HE, MAC).text == "שלום, מה קורה?"
    assert convert("שלום, מה קורה?", Direction.HE_TO_EN, MAC).text == "akuo' nv eurv?"
    assert convert("יקךךם", Direction.HE_TO_EN, MAC).text == "hello"


def test_mac_hebrew_differs_from_windows_where_apple_differs():
    # Mac "Hebrew": W types ׳ (geresh), not the apostrophe of the Windows layout.
    assert convert("w", Direction.EN_TO_HE, MAC).text == "׳"
    assert convert("w", Direction.EN_TO_HE).text == "'"  # Windows table unchanged
    assert convert("׳", Direction.HE_TO_EN, MAC).text == "w"


def test_strict_one_to_one_and_length_preserved():
    for table in MAC:
        assert all(len(k) == 1 and len(v) == 1 for k, v in table.items())
    sample = "".join(BUILTIN_EN_TO_HE) + " 123 😀\n"
    out = convert(sample, Direction.EN_TO_HE, MAC).text
    assert len(out) == len(sample)
    for ch in "abcdefghijklmnopqrstuvwxyz,.;/'`[]":
        assert BUILTIN_HE_TO_EN[BUILTIN_EN_TO_HE[ch]] == ch


def test_capitals_without_a_hebrew_shift_character_stay():
    assert convert("A", Direction.EN_TO_HE, MAC).text == "A"


def test_builtin_rows_cover_every_layout_key_once():
    codes = [r[0] for r in BUILTIN_ROWS]
    assert sorted(codes) == sorted(LAYOUT_KEYCODES) == sorted(ISO_KEYCODES.values())
    assert LAYOUT_KEYCODES[-1] == 10  # the ISO-only key is read last


def test_build_tables_first_key_wins_and_skips_multichar():
    en_he, he_en = build_tables([(1, "a", "A", "x", "xy"), (2, "b", "B", "x", "Z")])
    assert en_he == {"a": "x", "b": "x", "B": "Z"}
    assert he_en == {"x": "a", "Z": "B"}


def test_rows_from_readers_and_builtin_fallback():
    read = lambda layout: (lambda kc, shift: LAYOUTS[layout].get(kc, ("", ""))[shift])  # noqa: E731
    rows = rows_for("en", read("com.apple.keylayout.ABC"), None)
    assert dict((r[0], r[3]) for r in rows)[0] == "ש"  # Hebrew side from the built-in table
    en_he, _ = tables_for("en", read("com.apple.keylayout.ABC"), read("com.apple.keylayout.Hebrew-QWERTY"))
    assert en_he["a"] == "א" and en_he["h"] == "ה" and "e" not in en_he
    _, he_en = tables_for("he", read("com.apple.keylayout.Hebrew-QWERTY"), read("com.apple.keylayout.ABC"))
    assert he_en["א"] == "a"


def test_source_language():
    assert SourceInfo("x", "x", ("he",), True, True, True).lang == "he"
    assert SourceInfo("x", "x", ("iw",), True, True, True).lang == "he"
    assert SourceInfo("x", "x", ("en-US", "fr"), True, True, True).lang == "en"
    assert SourceInfo("x", "x", ("ru",), True, True, True).lang is None
    assert SourceInfo("x", "x", (), True, True, True).lang is None


def test_pick_layout_prefers_apple_layouts():
    srcs = [source("com.apple.keylayout.Hebrew-QWERTY"), source("com.apple.keylayout.Hebrew"),
            source("com.apple.keylayout.US"), source("com.apple.keylayout.ABC")]
    assert pick_layout(srcs, "he").id == "com.apple.keylayout.Hebrew"
    assert pick_layout(srcs, "en").id == "com.apple.keylayout.ABC"
    assert pick_layout([source("com.apple.keylayout.Hebrew-QWERTY")], "he").id.endswith("QWERTY")
    assert pick_layout([source("com.apple.keylayout.Russian")], "he") is None


def test_choose_pair_reads_installed_layout_when_not_in_input_menu():
    abc = source("com.apple.keylayout.ABC")
    pair = choose_pair(abc, [abc], [abc, source("com.apple.keylayout.Hebrew", enabled=False)], "he")
    assert pair.target is None and pair.target_id == "com.apple.keylayout.Hebrew"
