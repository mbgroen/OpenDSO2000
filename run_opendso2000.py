"""Frozen-app entry point for PyInstaller.

Starts the OpenDSO2000 web server. When run as a bundled binary with no
arguments it also opens the local browser, so double-clicking the app "just
works"; pass --host/--port/--no-open to override.
"""

import sys

from opendso2000.server.__main__ import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if getattr(sys, "frozen", False) and not argv:
        argv = ["--open"]
    raise SystemExit(main(argv))
