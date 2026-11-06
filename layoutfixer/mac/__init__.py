"""macOS platform layer (the Windows one lives in win/, win_env.py, targets/native_edit.py, uia*.py).

Only the modules that talk to macOS import PyObjC, and they do it lazily, so the
pure logic (shortcut parsing, chord detection, key tables, the Accessibility
target) is importable - and tested - on any platform.
"""
