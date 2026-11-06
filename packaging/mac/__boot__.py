"""First Python code that runs inside "Layout Fixer.app".

The app's launcher (py2app's prebuilt stub, Contents/MacOS/LayoutFixer) loads the
bundled Python into its own process - so macOS sees the app, not "python" - sets
PYTHONHOME and RESOURCEPATH to Contents/Resources and runs this file.
"""

import os
import sys

import site

resources = os.environ.get("RESOURCEPATH") or os.path.dirname(os.path.abspath(__file__))
os.environ["LAYOUTFIXER_APP_BUNDLE"] = os.path.dirname(os.path.dirname(resources))  # for start at login
# Only the bundle's own packages: not those the user installed for their own Python 3.13.
user_site = site.getusersitepackages()
if user_site:
    sys.path[:] = [p for p in sys.path if not p.startswith(user_site)]
sys.path.insert(0, os.path.join(resources, "app"))
# Older macOS versions pass "-psn_0_NNN" when the app is opened from the Finder.
sys.argv[1:] = [a for a in sys.argv[1:] if not a.startswith("-psn_")]

try:
    from layoutfixer.app import main
    code = main()
except SystemExit:
    raise
except BaseException:
    import traceback
    try:
        logs = os.path.expanduser("~/Library/Logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "LayoutFixer-crash.log"), "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except OSError:
        pass
    raise
sys.exit(code)
