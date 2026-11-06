"""Verify a built LayoutFixer.exe: run its --selftest, then start it in tray mode with a throw-away
data folder and the feature DISABLED (no shortcut registered), check it stays up and logs a clean
start, and stop it (whole process tree - the one-file exe runs as a parent + child process).

Exit codes: 0 passed, 1 failed, 3 Windows blocked the executable (application control).
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = 3


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "LayoutFixer.exe"
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "selftest.json"
        try:
            code = subprocess.run([str(exe), "--selftest", str(report)], timeout=180).returncode
        except OSError as e:
            print(f"could not start {exe}: {e}")
            return BLOCKED if getattr(e, "winerror", 0) in (1260, 4551, 5) else 1
        if not report.exists():
            print(f"self-test produced no report (exit code {code})")
            return 1
        result = json.loads(report.read_text(encoding="utf-8"))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if code != 0 or not result.get("ok"):
            return 1

        data = Path(tmp) / "data"
        data.mkdir()
        (data / "settings.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
        env = dict(__import__("os").environ, LAYOUTFIXER_DATA_DIR=str(data))
        proc = subprocess.Popen([str(exe), "--background"], env=env)
        try:
            time.sleep(6)
            alive = proc.poll() is None
        finally:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            proc.wait(10)
        log_file = data / "logs" / "layoutfixer.log"
        for _ in range(50):  # the child may need a moment to release the log file
            try:
                log = log_file.read_text(encoding="utf-8")
                break
            except OSError:
                time.sleep(0.1)
        else:
            log = ""
        print(log)
        ok = alive and "starting" in log and "registered" not in log and "ERROR" not in log \
            and "Traceback" not in log
        print("tray start-up:", "OK" if ok else "FAILED")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
