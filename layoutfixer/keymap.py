"""Physical key table for the Windows "US" and "Hebrew" keyboard layouts.

Each row is one physical key, identified by its scan code, with the character
it produces on each layout without and with Shift. The values were read from
Windows itself with ToUnicodeEx (layouts 00000409 "US", 0000040D "Hebrew" and
0002040D "Hebrew (Standard)" - the last two are identical on these layers);
tests/test_windows_layouts.py re-reads the installed layouts and compares.

This is a key-position mapping, not a translation: "akuo" is what the keys
for "שלום" type on the US layout.
"""

from __future__ import annotations

# (scan code, US, US + Shift, Hebrew, Hebrew + Shift)
KEYS: tuple[tuple[int, str, str, str, str], ...] = (
    (0x29, "`", "~", ";", "~"),
    (0x02, "1", "!", "1", "!"),
    (0x03, "2", "@", "2", "@"),
    (0x04, "3", "#", "3", "#"),
    (0x05, "4", "$", "4", "$"),
    (0x06, "5", "%", "5", "%"),
    (0x07, "6", "^", "6", "^"),
    (0x08, "7", "&", "7", "&"),
    (0x09, "8", "*", "8", "*"),
    (0x0A, "9", "(", "9", ")"),
    (0x0B, "0", ")", "0", "("),
    (0x0C, "-", "_", "-", "_"),
    (0x0D, "=", "+", "=", "+"),
    (0x10, "q", "Q", "/", "Q"),
    (0x11, "w", "W", "'", "W"),
    (0x12, "e", "E", "ק", "E"),  # ק
    (0x13, "r", "R", "ר", "R"),  # ר
    (0x14, "t", "T", "א", "T"),  # א
    (0x15, "y", "Y", "ט", "Y"),  # ט
    (0x16, "u", "U", "ו", "U"),  # ו
    (0x17, "i", "I", "ן", "I"),  # ן
    (0x18, "o", "O", "ם", "O"),  # ם
    (0x19, "p", "P", "פ", "P"),  # פ
    (0x1A, "[", "{", "]", "}"),
    (0x1B, "]", "}", "[", "{"),
    (0x1E, "a", "A", "ש", "A"),  # ש
    (0x1F, "s", "S", "ד", "S"),  # ד
    (0x20, "d", "D", "ג", "D"),  # ג
    (0x21, "f", "F", "כ", "F"),  # כ
    (0x22, "g", "G", "ע", "G"),  # ע
    (0x23, "h", "H", "י", "H"),  # י
    (0x24, "j", "J", "ח", "J"),  # ח
    (0x25, "k", "K", "ל", "K"),  # ל
    (0x26, "l", "L", "ך", "L"),  # ך
    (0x27, ";", ":", "ף", ":"),  # ף
    (0x28, "'", '"', ",", '"'),
    (0x2B, "\\", "|", "\\", "|"),
    (0x2C, "z", "Z", "ז", "Z"),  # ז
    (0x2D, "x", "X", "ס", "X"),  # ס
    (0x2E, "c", "C", "ב", "C"),  # ב
    (0x2F, "v", "V", "ה", "V"),  # ה
    (0x30, "b", "B", "נ", "B"),  # נ
    (0x31, "n", "N", "מ", "N"),  # מ
    (0x32, "m", "M", "צ", "M"),  # צ
    (0x33, ",", "<", "ת", ">"),  # ת
    (0x34, ".", ">", "ץ", "<"),  # ץ
    (0x35, "/", "?", ".", "?"),
    (0x39, " ", " ", " ", " "),
)


def _build() -> tuple[dict[str, str], dict[str, str]]:
    en_he: dict[str, str] = {}
    he_en: dict[str, str] = {}
    for _sc, us, us_sh, he, he_sh in KEYS:
        for en_ch, he_ch in ((us, he), (us_sh, he_sh)):
            if en_he.get(en_ch) == he_ch and he_en.get(he_ch) == en_ch:
                continue  # Space: same character with and without Shift
            if en_ch in en_he or he_ch in he_en:
                raise ValueError(f"duplicate character in key table: {en_ch!r}/{he_ch!r}")
            en_he[en_ch] = he_ch
            he_en[he_ch] = en_ch
    return en_he, he_en


# Strict physical mappings (bijective; identity entries included).
PHYSICAL_EN_TO_HE, PHYSICAL_HE_TO_EN = _build()
