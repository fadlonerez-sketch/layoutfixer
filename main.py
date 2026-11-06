"""Entry point (source runs, PyInstaller and the portable build)."""

import sys

from layoutfixer.app import main

if __name__ == "__main__":
    sys.exit(main())
