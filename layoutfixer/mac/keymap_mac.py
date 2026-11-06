"""Key tables for macOS layouts.

macOS layouts are not the Windows ones: the Mac "Hebrew" layout types ׳ (geresh) on
the W key and a rafe on the backslash key, its Shift layer has no Latin capitals,
and "Hebrew - QWERTY" is phonetic. So on a Mac the conversion uses the layouts
that are actually installed there: mac/layouts.py reads every key of the active
layout and of the layout to switch to with UCKeyTranslate (like Windows'
ToUnicodeEx in win/layouts.py) and builds the tables with ``build_tables``.

``BUILTIN_ROWS`` is the fallback when a layout cannot be read (e.g. no Hebrew
layout is installed yet): macOS "U.S." / "ABC" and macOS "Hebrew", taken from
Unicode CLDR's macOS keyboard data (keyboards/osx/en-t-k0-osx.xml and
he-t-k0-osx.xml, release 43). "" = the key types nothing, or more than one
character, on that layer.

The conversion stays strict key-for-key and 1:1: every character maps to exactly
one character. Where two keys of a layout type the same character, the
unshifted key wins, then the first key in ``LAYOUT_KEYCODES`` order.
"""

from __future__ import annotations

from typing import Iterable

# (key code, U.S., U.S. + Shift, Hebrew, Hebrew + Shift)
BUILTIN_ROWS: tuple[tuple[int, str, str, str, str], ...] = (
    (50, "`", "~", ";", "~"),
    (18, "1", "!", "1", "!"),
    (19, "2", "@", "2", "@"),
    (20, "3", "#", "3", "#"),
    (21, "4", "$", "4", "$"),
    (23, "5", "%", "5", "%"),
    (22, "6", "^", "6", "^"),
    (26, "7", "&", "7", "₪"),
    (28, "8", "*", "8", "*"),
    (25, "9", "(", "9", ")"),
    (29, "0", ")", "0", "("),
    (27, "-", "_", "-", "_"),
    (24, "=", "+", "=", "+"),
    (12, "q", "Q", "/", ""),
    (13, "w", "W", "׳", ""),       # ׳ geresh
    (14, "e", "E", "ק", ""),
    (15, "r", "R", "ר", ""),
    (17, "t", "T", "א", ""),
    (16, "y", "Y", "ט", ""),
    (32, "u", "U", "ו", ""),
    (34, "i", "I", "ן", ""),
    (31, "o", "O", "ם", ""),
    (35, "p", "P", "פ", ""),
    (33, "[", "{", "]", "}"),
    (30, "]", "}", "[", "{"),
    (42, "\\", "|", "ֿ", "|"),     # ֿ rafe
    (0, "a", "A", "ש", ""),
    (1, "s", "S", "ד", ""),
    (2, "d", "D", "ג", "„"),
    (3, "f", "F", "כ", ""),
    (5, "g", "G", "ע", ""),
    (4, "h", "H", "י", ""),
    (38, "j", "J", "ח", ""),
    (40, "k", "K", "ל", ""),
    (37, "l", "L", "ך", ""),
    (41, ";", ":", "ף", ":"),
    (39, "'", '"', ",", "״"),      # ״ gershayim
    (6, "z", "Z", "ז", ""),
    (7, "x", "X", "ס", ""),
    (8, "c", "C", "ב", ""),
    (9, "v", "V", "ה", ""),
    (11, "b", "B", "נ", ""),
    (45, "n", "N", "מ", ""),
    (46, "m", "M", "צ", ""),
    (43, ",", "<", "ת", ">"),
    (47, ".", ">", "ץ", "<"),
    (44, "/", "?", ".", "?"),
    (49, " ", " ", " ", " "),
    (10, "§", "±", "", ""),         # the extra ISO key next to Z (not on US-shaped keyboards)
)


def usable(ch: str) -> bool:
    return len(ch) == 1 and (ch == " " or ch.isprintable())


def build_tables(rows: Iterable[tuple[int, str, str, str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    """(en -> he, he -> en) from per-key rows (key code, en, en + Shift, he, he + Shift)."""
    rows = list(rows)
    en_he: dict[str, str] = {}
    he_en: dict[str, str] = {}
    for shift in (0, 1):
        for row in rows:
            en, he = row[1 + shift], row[3 + shift]
            if usable(en) and usable(he):
                en_he.setdefault(en, he)
                he_en.setdefault(he, en)
    return en_he, he_en


BUILTIN_EN_TO_HE, BUILTIN_HE_TO_EN = build_tables(BUILTIN_ROWS)
