"""Run the OpenDSO2000 web server.

    python -m opendso2000.server [--host 0.0.0.0] [--port 8000] [--open]

Point a browser on any device on the network at http://<server-ip>:<port>/.
Set OPENDSO2000_TOKEN to require a shared secret.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser


def _port_in_use(host: str, port: int) -> bool:
    """True if something is already listening (e.g. a previous launch)."""
    test_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((test_host, port)) == 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="opendso2000.server",
                                description="OpenDSO2000 web server.")
    p.add_argument("--host", default="0.0.0.0",
                   help="Interface to bind (default: all interfaces).")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    p.add_argument("--open", action="store_true",
                   help="Open the UI in the local browser on start.")
    args = p.parse_args(argv)

    url = f"http://localhost:{args.port}/"

    # Already running (e.g. the app was double-clicked twice, or both the ARM and
    # Intel builds were launched)? Don't crash — just open the existing UI.
    if _port_in_use(args.host, args.port):
        print(f"[OpenDSO2000] A server is already running on port {args.port}; "
              f"opening {url}")
        webbrowser.open(url)
        return 0

    import uvicorn
    from .app import app

    print(f"[OpenDSO2000] Web UI on http://{args.host}:{args.port}/  "
          f"(open {url} or http://<this-host-ip>:{args.port}/ from another device)")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except OSError as exc:                       # port grabbed in a race, etc.
        print(f"[OpenDSO2000] Could not bind {args.host}:{args.port}: {exc}\n"
              f"Opening {url} in case another instance owns it.")
        webbrowser.open(url)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
