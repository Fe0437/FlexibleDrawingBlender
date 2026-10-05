#!/usr/bin/env python3
"""Run the packaged extension in Blender against a Realtime Plane, the way a person would.

It packages the extension with its wheels, installs it into a throwaway Blender profile, and runs
`blender_realtime_plane_session.py` inside Blender. In the background the Realtime Plane is the
headless stand-in (`--peer`); with `--interactive`, Blender opens a window and launches the real,
bundled Realtime Plane (`--build-dir` to install it from), which needs a desktop session with a GPU.

Every run uses a scope of its own, so it never attaches to the Realtime Plane of the person at the
machine, and it stops whatever Realtime Plane is left in that scope when it ends.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from packaged_blender import MODULE, Install, StopLeftovers

HERE = Path(__file__).resolve().parent
MARKER = "FLEXIBLE_DRAWING_REALTIME_PLANE_OK"


def main() -> int:
    """Package, run Blender, and report what it printed when it failed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--package-script", type=Path, required=True)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--peer", type=Path, help="the headless stand-in's host-session peer")
    parser.add_argument("--interactive", action="store_true", help="open a window and run the real Realtime Plane")
    parser.add_argument("--build-dir", type=Path, help="the build to install the real Realtime Plane from")
    args = parser.parse_args()
    if args.interactive == (args.peer is not None) or (args.interactive and args.build_dir is None):
        parser.error("pass --peer, or --interactive with --build-dir")

    scope = f"blender-test-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="flexible-drawing-realtime-plane-") as directory:
        root = Path(directory)
        environment = Install(root, args, scope, buildDir=args.build_dir if args.interactive else None)
        if args.peer is not None:
            standIn = [sys.executable, str(HERE / "realtime_plane_stand_in.py"), "--peer", str(args.peer)]
            environment["FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND"] = shlex.join(standIn)
        try:
            completed = subprocess.run(
                [
                    str(args.blender),
                    *([] if args.interactive else ["--background"]),
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(HERE / "blender_realtime_plane_session.py"),
                    "--",
                    "--module",
                    MODULE,
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        finally:
            StopLeftovers(root, scope)
    output = completed.stdout + completed.stderr
    if completed.returncode != 0 or MARKER not in output:
        print(output, file=sys.stderr)
        print(f"FAIL: Blender exited with {completed.returncode} before {MARKER}", file=sys.stderr)
        return 1
    print(f"{MARKER} ({'real Realtime Plane, with a window' if args.interactive else 'stand-in, background'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
