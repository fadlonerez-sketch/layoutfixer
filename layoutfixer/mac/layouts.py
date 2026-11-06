"""Which Mac layouts a conversion goes between, and their key tables (pure logic; TIS calls are passed in).

The source layout is the one active when the shortcut was pressed. The target
is the layout of the other language the user switches to: an enabled one
(input menu) if there is one - preferring Apple's "Hebrew" / "ABC" / "U.S." -
otherwise an installed one, only for reading its keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Sequence

from .keycodes import LAYOUT_KEYCODES
from .keymap_mac import BUILTIN_ROWS, build_tables
from .tis import SourceInfo

log = logging.getLogger(__name__)

PREFERRED = {
    "he": ("com.apple.keylayout.Hebrew", "com.apple.keylayout.Hebrew-PC", "com.apple.keylayout.Hebrew-QWERTY"),
    "en": ("com.apple.keylayout.ABC", "com.apple.keylayout.US", "com.apple.keylayout.British",
           "com.apple.keylayout.Australian", "com.apple.keylayout.Canadian"),
}
LANG_LABEL = {"he": "Hebrew", "en": "English"}


def pick_layout(sources: Sequence[SourceInfo], lang: str) -> SourceInfo | None:
    """The layout of ``lang`` to switch to: preferred Apple ones first, then the first in the list."""
    matches = [s for s in sources if s.lang == lang and s.is_layout]
    for wanted in PREFERRED[lang]:
        for s in matches:
            if s.id == wanted:
                return s
    return matches[0] if matches else None


@dataclass(frozen=True)
class Pair:
    source: SourceInfo           # active when the shortcut was pressed
    target: SourceInfo | None    # enabled layout of the other language (None: not in the input menu)
    target_id: str               # layout whose keys are read (target, or an installed one)


def choose_pair(source: SourceInfo, enabled: Sequence[SourceInfo], installed: Sequence[SourceInfo],
                target_lang: str) -> Pair:
    target = pick_layout(enabled, target_lang)
    read_from = target or pick_layout(installed, target_lang)
    return Pair(source, target, read_from.id if read_from else "")


def rows_for(source_lang: str, read_source: Callable[[int, bool], str] | None,
             read_target: Callable[[int, bool], str] | None) -> list[tuple[int, str, str, str, str]]:
    """Per-key rows (key code, en, en + Shift, he, he + Shift). A side that cannot be read
    (``None``) comes from the built-in Mac table."""
    builtin = {row[0]: row for row in BUILTIN_ROWS}
    read_en, read_he = (read_source, read_target) if source_lang == "en" else (read_target, read_source)
    rows = []
    for kc in LAYOUT_KEYCODES:
        b = builtin.get(kc, (kc, "", "", "", ""))
        en = (read_en(kc, False), read_en(kc, True)) if read_en else (b[1], b[2])
        he = (read_he(kc, False), read_he(kc, True)) if read_he else (b[3], b[4])
        rows.append((kc, en[0], en[1], he[0], he[1]))
    return rows


def tables_for(source_lang: str, read_source, read_target) -> tuple[dict[str, str], dict[str, str]]:
    return build_tables(rows_for(source_lang, read_source, read_target))
