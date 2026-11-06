"""macOS virtual key codes (kVK_* from HIToolbox/Events.h) and event modifier flags (CGEventFlags).

Key codes name physical key positions (kVK_ANSI_A is the key labelled A on a US
keyboard, whatever layout is active), like Windows scan codes.
"""

from __future__ import annotations

# Device-independent modifier bits of CGEventFlags / NSEvent.modifierFlags.
FLAG_CAPSLOCK = 0x00010000
FLAG_SHIFT = 0x00020000
FLAG_CONTROL = 0x00040000
FLAG_OPTION = 0x00080000
FLAG_COMMAND = 0x00100000
FLAG_FN = 0x00800000          # kCGEventFlagMaskSecondaryFn: the Fn / Globe key
FLAG_NUMERICPAD = 0x00200000

MODIFIER_FLAGS = FLAG_SHIFT | FLAG_CONTROL | FLAG_OPTION | FLAG_COMMAND | FLAG_FN

# Display order of macOS menus: Fn, Control, Option, Shift, Command.
MODIFIER_NAMES = ((FLAG_FN, "Fn"), (FLAG_CONTROL, "Ctrl"), (FLAG_OPTION, "Option"), (FLAG_SHIFT, "Shift"),
                  (FLAG_COMMAND, "Cmd"))
MODIFIER_SYMBOLS = {FLAG_FN: "Fn", FLAG_CONTROL: "⌃", FLAG_OPTION: "⌥", FLAG_SHIFT: "⇧", FLAG_COMMAND: "⌘"}
MODIFIER_ALIASES = {"cmd": FLAG_COMMAND, "command": FLAG_COMMAND, "⌘": FLAG_COMMAND,
                    "ctrl": FLAG_CONTROL, "control": FLAG_CONTROL, "⌃": FLAG_CONTROL,
                    "option": FLAG_OPTION, "opt": FLAG_OPTION, "alt": FLAG_OPTION, "⌥": FLAG_OPTION,
                    "shift": FLAG_SHIFT, "⇧": FLAG_SHIFT,
                    "fn": FLAG_FN, "globe": FLAG_FN, "function": FLAG_FN}

# Key codes of the modifier keys themselves (flagsChanged events carry these).
MODIFIER_KEYCODES = {54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 179}  # 63 = Fn, 179 = Globe on newer keyboards

KEY_NAMES: dict[str, int] = {
    "A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7, "C": 8, "V": 9, "B": 11, "Q": 12,
    "W": 13, "E": 14, "R": 15, "Y": 16, "T": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "O": 31, "U": 32, "[": 33, "I": 34,
    "P": 35, "L": 37, "J": 38, "'": 39, "K": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "N": 45, "M": 46,
    ".": 47, "`": 50,
    "Return": 36, "Tab": 48, "Space": 49, "Delete": 51, "Escape": 53, "ForwardDelete": 117,
    "Home": 115, "End": 119, "PageUp": 116, "PageDown": 121,
    "Left": 123, "Right": 124, "Down": 125, "Up": 126,
    "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97, "F7": 98, "F8": 100, "F9": 101,
    "F10": 109, "F11": 103, "F12": 111, "F13": 105, "F14": 107, "F15": 113, "F16": 106, "F17": 64,
    "F18": 79, "F19": 80, "F20": 90,
}
KEYCODE_TO_NAME = {code: name for name, code in KEY_NAMES.items()}
KEY_ALIASES = {"esc": "Escape", "enter": "Return", "backspace": "Delete", "del": "ForwardDelete",
               "spacebar": "Space", "pgup": "PageUp", "pgdn": "PageDown"}
FUNCTION_KEYS = {f"F{i}" for i in range(1, 21)}
TYPING_KEYS = {n for n in KEY_NAMES if len(n) == 1} | {"Space", "Return", "Tab", "Delete"}

KC_C = KEY_NAMES["C"]
KC_V = KEY_NAMES["V"]
KC_ESCAPE = KEY_NAMES["Escape"]
KC_DELETE = KEY_NAMES["Delete"]
KC_FORWARD_DELETE = KEY_NAMES["ForwardDelete"]

# The typing keys of the main block in ISO position order (CLDR names: row E = digits, D = QWERTY,
# C = ASDF, B = ZXCV, A03 = space). B00 is the extra ISO key left of Z (kVK_ISO_Section).
ISO_KEYCODES: dict[str, int] = {
    "E00": 50, "E01": 18, "E02": 19, "E03": 20, "E04": 21, "E05": 23, "E06": 22, "E07": 26, "E08": 28,
    "E09": 25, "E10": 29, "E11": 27, "E12": 24,
    "D01": 12, "D02": 13, "D03": 14, "D04": 15, "D05": 17, "D06": 16, "D07": 32, "D08": 34, "D09": 31,
    "D10": 35, "D11": 33, "D12": 30, "D13": 42,
    "C01": 0, "C02": 1, "C03": 2, "C04": 3, "C05": 5, "C06": 4, "C07": 38, "C08": 40, "C09": 37,
    "C10": 41, "C11": 39,
    "B00": 10, "B01": 6, "B02": 7, "B03": 8, "B04": 9, "B05": 11, "B06": 45, "B07": 46, "B08": 43,
    "B09": 47, "B10": 44,
    "A03": 49,
}
# Keys read from a layout, in priority order: the ISO-only key goes last, so where it types the same
# character as another key, the key every keyboard has wins.
LAYOUT_KEYCODES: tuple[int, ...] = tuple(k for k in ISO_KEYCODES.values() if k != 10) + (10,)

# Marks our own synthetic ⌘C / ⌘V (kCGEventSourceUserData) so the event tap ignores them.
INJECTED_MARK = 0x4C46_5846  # "LFXF", as on Windows
