"""Run the OpenDSO2000 web server.

    python -m opendso2000.server [--host 0.0.0.0] [--port 8000] [--open]

Point a browser on any device on the network at http://<server-ip>:<port>/.
Set OPENDSO2000_TOKEN to require a shared secret.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="opendso2000.server",
                                description="OpenDSO2000 web server.")
    p.add_argument("--host", default="0.0.0.0",
                   help="Interface to bind (default: all interfaces).")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    p.add_argument("--open", action="store_true",
                   help="Open the UI in the local browser on start.")
    args = p.parse_args(argv)

    import uvicorn
    from .app import app

    url = f"http://localhost:{args.port}/"
    print(f"[OpenDSO2000] Web UI on http://{args.host}:{args.port}/  "
          f"(open {url} or http://<this-host-ip>:{args.port}/ from another device)")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
