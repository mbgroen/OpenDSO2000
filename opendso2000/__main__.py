"""``python -m opendso2000`` launches the web server.

OpenDSO2000 is a client/server app: this starts the server (which talks to the
scope) and serves the browser UI. Open the printed URL from any device on the
network. See ``python -m opendso2000.server --help`` for options.
"""

from .server.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
