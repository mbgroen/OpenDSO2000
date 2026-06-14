"""Allow ``python -m opendso2000``."""

from .ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
