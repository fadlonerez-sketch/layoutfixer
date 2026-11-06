"""Wrong-layout conversion: a strict key-for-key mapping. Pure Python, no Windows calls.

The direction comes from the keyboard layout that is active in the target window:
text typed with the US layout is converted to what the same keys type on the
Hebrew layout, and the other way round. There is no language detection and no
rule about words, links or punctuation - every character that has a key on the
source layout becomes the character of that key (same Shift state) on the other
layout; anything else (digits, spaces, line breaks, emoji...) stays as it is.
The order of the characters never changes.

Every character maps to exactly one character, so a conversion never changes
the length of the text (in code points or UTF-16 units). The text-access code
relies on that to replace only the span that changed and to put the caret back.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .keymap import PHYSICAL_EN_TO_HE, PHYSICAL_HE_TO_EN


class Direction(str, Enum):
    EN_TO_HE = "en>he"
    HE_TO_EN = "he>en"

    @property
    def target_lang(self) -> str:
        return "he" if self is Direction.EN_TO_HE else "en"

    @property
    def source_lang(self) -> str:
        return "en" if self is Direction.EN_TO_HE else "he"

    @property
    def label(self) -> str:
        return "Hebrew" if self is Direction.EN_TO_HE else "English"


def direction_for_layout(lang: str | None) -> Direction | None:
    """English layout active -> convert to Hebrew; Hebrew layout active -> convert to English."""
    if lang == "en":
        return Direction.EN_TO_HE
    if lang == "he":
        return Direction.HE_TO_EN
    return None


@dataclass(frozen=True)
class Conversion:
    source: str
    text: str
    direction: Direction

    @property
    def changed(self) -> bool:
        return self.text != self.source


def convert(text: str, direction: Direction,
            tables: tuple[dict[str, str], dict[str, str]] | None = None) -> Conversion:
    """``tables``: (en -> he, he -> en) of other layouts (macOS); default: the Windows US / Hebrew keys."""
    en_he, he_en = tables or (PHYSICAL_EN_TO_HE, PHYSICAL_HE_TO_EN)
    table = en_he if direction is Direction.EN_TO_HE else he_en
    result = "".join(table.get(ch, ch) for ch in text)
    assert len(result) == len(text)
    return Conversion(text, result, direction)
