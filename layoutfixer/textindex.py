"""Index conversion between Python strings and Windows edit-control positions.

Edit controls count UTF-16 code units (an emoji is 2, CR LF is 2). RichEdit
controls count UTF-16 code units too, but a CR LF line break is a single
position even though WM_GETTEXT returns both characters.
"""

from __future__ import annotations


def _width(text: str, i: int, crlf_as_one: bool) -> int:
    ch = text[i]
    if crlf_as_one and ch == "\n" and i > 0 and text[i - 1] == "\r":
        return 0
    return 2 if ord(ch) > 0xFFFF else 1


def to_units(text: str, index: int, crlf_as_one: bool = False) -> int:
    """Control position of Python index ``index`` (0..len(text))."""
    units = 0
    for i in range(min(index, len(text))):
        units += _width(text, i, crlf_as_one)
    return units


def from_units(text: str, units: int, crlf_as_one: bool = False) -> int:
    """Python index for control position ``units``; positions inside a character snap forward."""
    pos = 0
    for i in range(len(text)):
        if pos >= units:
            if crlf_as_one and text[i] == "\n" and i > 0 and text[i - 1] == "\r":
                continue  # the LF of CR LF has no position of its own
            return i
        pos += _width(text, i, crlf_as_one)
    return len(text)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
