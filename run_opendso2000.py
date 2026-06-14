"""Frozen-app entry point for PyInstaller.

Kept at the repo root as a stable, importable launcher target so the bundled
binary starts the same code path as ``python -m opendso2000``.
"""

from opendso2000.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
