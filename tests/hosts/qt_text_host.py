"""Test host: Qt text widgets in their own process, exposed through UI Automation.

The window is placed far off-screen and shown without activation, so it never
appears or takes focus. Tests read and select text through real UI Automation;
"paste" (what Ctrl+V would do) is simulated by a stdin command, because tests
must not inject real keystrokes.

stdin commands (JSON per line): {"cmd": "set"|"select"|"paste"|"state", "w": name, ...}
stdout: one JSON line per command, first line = {"hwnd": ..., "pid": ...}
"""

import json
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget


def main():
    app = QApplication(sys.argv)
    win = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                  | Qt.WindowType.WindowDoesNotAcceptFocus)
    win.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    win.setWindowTitle("LayoutFixer UIA test host")
    widgets = {
        "line": QLineEdit(),
        "plain": QPlainTextEdit(),
        "rich": QTextEdit(),
        "readonly": QLineEdit(),
        "password": QLineEdit(),
    }
    widgets["readonly"].setReadOnly(True)
    widgets["password"].setEchoMode(QLineEdit.EchoMode.Password)
    lay = QVBoxLayout(win)
    for name, w in widgets.items():
        w.setAccessibleName("lf-" + name)
        w.setObjectName(name)
        lay.addWidget(w)
    win.setGeometry(-30000, -30000, 400, 400)
    win.show()

    def text_of(w):
        return w.text() if isinstance(w, QLineEdit) else w.toPlainText()

    def sel_of(w):
        if isinstance(w, QLineEdit):
            if w.hasSelectedText():
                return [w.selectionStart(), w.selectionEnd()]
            return [w.cursorPosition(), w.cursorPosition()]
        c = w.textCursor()
        return [c.selectionStart(), c.selectionEnd()]

    def handle(line):
        req = json.loads(line)
        cmd = req["cmd"]
        w = widgets.get(req.get("w", "line"))
        if cmd == "set":
            if isinstance(w, QLineEdit):
                w.setText(req["text"])
            else:
                w.setPlainText(req["text"])
        elif cmd == "select":
            a, b = req["a"], req["b"]
            if isinstance(w, QLineEdit):
                w.setSelection(a, b - a)
            else:
                c = w.textCursor()
                c.setPosition(a)
                c.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
                w.setTextCursor(c)
        elif cmd == "paste":  # what Ctrl+V does: replace the selection with the text
            if isinstance(w, QLineEdit):
                w.insert(req["text"])
            else:
                w.textCursor().insertText(req["text"])
        elif cmd == "html":
            w.setHtml(req["html"])
        elif cmd == "images":
            print(json.dumps({"images": w.toHtml().count("<img")}), flush=True)
            return
        elif cmd == "quit":
            app.quit()
            return
        print(json.dumps({"text": text_of(w), "sel": sel_of(w)}), flush=True)

    buf = []

    def poll_stdin():
        # stdin is a pipe; read lines without blocking the event loop for long
        import msvcrt
        import ctypes
        from ctypes import wintypes as W
        h = msvcrt.get_osfhandle(sys.stdin.fileno())
        avail = W.DWORD()
        while ctypes.windll.kernel32.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None) and avail.value:
            chunk = os.read(sys.stdin.fileno(), avail.value).decode("utf-8")
            buf.append(chunk)
            data = "".join(buf)
            *lines, rest = data.split("\n")
            buf[:] = [rest]
            for ln in lines:
                if ln.strip():
                    handle(ln)
        if not ctypes.windll.kernel32.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None):
            app.quit()  # parent went away

    timer = QTimer()
    timer.timeout.connect(poll_stdin)
    timer.start(5)
    print(json.dumps({"hwnd": int(win.winId()), "pid": os.getpid()}), flush=True)
    app.exec()


if __name__ == "__main__":
    main()
