"""The conversion itself: strict key-for-key, direction chosen by the active layout, no guessing."""

import random
import string

import pytest

from layoutfixer.converter import Direction, convert, direction_for_layout
from layoutfixer.keymap import KEYS

E2H, H2E = Direction.EN_TO_HE, Direction.HE_TO_EN


def to_he(s):
    return convert(s, E2H).text


def to_en(s):
    return convert(s, H2E).text


def test_direction_comes_only_from_the_active_layout():
    assert direction_for_layout("en") is E2H
    assert direction_for_layout("he") is H2E
    assert direction_for_layout(None) is None


def test_akuo_is_shalom():
    assert to_he("akuo") == "שלום"


def test_sentence_typed_with_the_right_keys():
    # שלום, מה קורה?  typed on the US layout (the Hebrew comma is on the ' key)
    assert to_he("akuo' nv eurv?") == "שלום, מה קורה?"


def test_example_from_the_request_is_converted_key_by_key():
    # "vn" are the keys of ה-מ and "euxv" of ק-ו-ס-ה; "," is the key of ת. No rules, just the keys.
    assert to_he("akuo, vn euxv?") == "שלוםת המ קוסה?"


def test_reverse_direction():
    assert to_en("יקךךם") == "hello"
    assert to_en("יקךךםת 'םרךגץ") == "hello, world."


def test_every_key_both_shift_states_round_trips():
    every = "".join(ch for row in KEYS for ch in row[1:3])
    assert to_en(to_he(every)) == every
    hebrew_side = "".join(ch for row in KEYS for ch in row[3:5])
    assert to_he(to_en(hebrew_side)) == hebrew_side


def test_punctuation_is_converted_like_any_other_key():
    assert to_he(",.;/'`") == "תץף.,;"
    assert to_en("תץף.,;") == ",.;/'`"
    assert to_he("1,000.5") == "1ת000ץ5"  # no exceptions for numbers


def test_shifted_characters_follow_the_hebrew_layout():
    # On the Hebrew layout Shift+9 types ")" and Shift+0 "(" (mirrored); Shift+letter types the capital.
    assert to_he("()<>{}") == ")(><}{"
    assert to_he("Akuo") == "Aלום"
    assert to_he("ABC") == "ABC"


def test_links_and_mixed_text_are_converted_mechanically():
    assert to_he("www.akuo.com") == "'''ץשלוםץבםצ"
    assert to_he("שלום akuo") == "שלום שלום"  # Hebrew letters have no key on the US layout: unchanged
    assert to_en("hello יקךךם") == "hello hello"


def test_order_is_preserved_character_by_character():
    text = "akuo nv eurv"
    out = to_he(text)
    assert [convert(ch, E2H).text for ch in text] == list(out)


@pytest.mark.parametrize("keep", ["0123456789", " \t\r\n", "😀", "é", "שָ"[1:]])
def test_characters_without_a_key_on_the_source_layout_pass_through(keep):
    assert to_he(keep) == keep
    assert to_en(keep) == keep


def test_length_is_always_preserved():
    rng = random.Random(7)
    pool = string.printable + "שלוםאבגדהוזחטיכלמנסעפצקרתךםןףץ😀￼"
    for _ in range(300):
        s = "".join(rng.choice(pool) for _ in range(rng.randint(0, 40)))
        for d in (E2H, H2E):
            c = convert(s, d)
            assert len(c.text) == len(s)
            assert c.changed == (c.text != s)
