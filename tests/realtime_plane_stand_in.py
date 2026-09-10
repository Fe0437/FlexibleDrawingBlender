#!/usr/bin/env python3
"""Stand in for the Realtime Plane: the same command line, served by the headless host-session peer.

The real Realtime Plane opens a window and reads a real pen, which a test machine may not have. The
Realtime Plane's own host-session peer serves the same session over the same transport while it
paints a continuous stroke with a fake pen, but it takes its service names from the environment and
stops when its input says so. This translates: it takes the Realtime Plane's `--...-service`
options, starts the peer, and ends it the way the Realtime Plane ends, on SIGTERM.

Run it as `python3 realtime_plane_stand_in.py --peer PEER [Realtime Plane options...]`.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys


def main() -> int:
    """Start the peer with the services named on the command line and serve until SIGTERM."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", required=True)
    for channel in ("control", "state", "tile", "result"):
        parser.add_argument(f"--{channel}-service", required=True)
    args = parser.parse_args()
    environment = {
        **os.environ,
        "FLEXIBLE_DRAWING_CONTROL_SERVICE": args.control_service,
        "FLEXIBLE_DRAWING_STATE_SERVICE": args.state_service,
        "FLEXIBLE_DRAWING_TILE_SERVICE": args.tile_service,
        "FLEXIBLE_DRAWING_RESULT_SERVICE": args.result_service,
    }
    peer = subprocess.Popen([args.peer], env=environment, stdin=subprocess.PIPE, text=True)

    def _stop(_signal: int, _frame: object) -> None:
        # The peer stops painting at its first line and exits at its second.
        peer.stdin.write("stop\nexit\n")
        peer.stdin.flush()

    signal.signal(signal.SIGTERM, _stop)
    return peer.wait()


if __name__ == "__main__":
    sys.exit(main())
