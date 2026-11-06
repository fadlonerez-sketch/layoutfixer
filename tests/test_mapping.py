"""The key table itself: complete, bijective, and identical to what Windows' layouts type."""

import string

import pytest

from layoutfixer.converter import Direction, convert
from layoutfixer.keymap import KEYS, PHYSICAL_EN_TO_HE, PHYSICAL_HE_TO_EN

HEB = {
    "q": "/", "w": "'", "e": "ק", "r": "ר", "t": "א", "y": "ט", "u": "ו", "i": "ן", "o": "ם", "p": "פ",
    "[": "]", "]": "[", "a": "ש", "s": "ד", "d": "ג", "f": "כ", "g": "ע", "h": "י", "j": "ח", "k": "ל",
    "l": "ך", ";": "ף", "'": ",", "z": "ז", "x": "ס", "c": "ב", "v": "ה", "b": "נ", "n": "מ", "m": "צ",
    ",": "ת", ".": "ץ", "/": ".", "`": ";",
}
SHIFTED = {"(": ")", ")": "(", "{": "}", "}": "{", "<": ">", ">": "<"}


def test_every_printable_us_character_is_mapped():
    printable = set(string.ascii_letters + string.digits + string.punctuation + " ")
    assert printable <= set(PHYSICAL_EN_TO_HE)


@pytest.mark.parametrize("en,he", sorted(HEB.items()))
def test_unshifted_layer(en, he):
    assert PHYSICAL_EN_TO_HE[en] == he
    assert PHYSICAL_HE_TO_EN[he] == en


@pytest.mark.parametrize("en,he", sorted(SHIFTED.items()))
def test_shift_layer_mirrored_brackets(en, he):
    assert PHYSICAL_EN_TO_HE[en] == he


def test_shift_layer_identity_for_symbols_and_capitals():
    for ch in "~!@#$%^&*_+:\"|?" + string.ascii_uppercase:
        assert PHYSICAL_EN_TO_HE[ch] == ch


def test_digits_identity():
    for d in string.digits:
        assert PHYSICAL_EN_TO_HE[d] == d == PHYSICAL_HE_TO_EN[d]


def test_mapping_is_a_bijection():
    assert len(PHYSICAL_EN_TO_HE) == len(PHYSICAL_HE_TO_EN)
    for en, he in PHYSICAL_EN_TO_HE.items():
        assert PHYSICAL_HE_TO_EN[he] == en


def test_all_27_hebrew_letters_have_a_key():
    letters = {chr(c) for c in range(0x05D0, 0x05EB)}
    assert len(letters) == 27
    assert letters <= set(PHYSICAL_HE_TO_EN)


def test_examples_from_spec():
    assert convert("c", Direction.EN_TO_HE).text == "ב"
    assert convert("v", Direction.EN_TO_HE).text == "ה"
    assert convert("a", Direction.EN_TO_HE).text == "ש"
    assert convert("k", Direction.EN_TO_HE).text == "ל"
    assert convert("akuo", Direction.EN_TO_HE).text == "שלום"


def test_physical_round_trip_all_keys():
    every = "".join(ch for row in KEYS for ch in row[1:3])
    there = convert(every, Direction.EN_TO_HE).text
    assert convert(there, Direction.HE_TO_EN).text == every
