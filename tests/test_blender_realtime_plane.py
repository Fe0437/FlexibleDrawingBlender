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
import shutil
import subprocess
import sys
import tempfile
import types

HERE = Path(__file__).resolve().parent
MARKER = "FLEXIBLE_DRAWING_REALTIME_PLANE_OK"


def _stopLeftovers(extension: Path, scope: str) -> None:
    """End a Realtime Plane a failed run left behind in its scope, and forget the scope."""
    root = types.ModuleType("flexible_drawing")
    root.__path__ = [str(extension)]
    sys.modules["flexible_drawing"] = root
    from flexible_drawing.realtime_plane import process

    running = process.Attach(process.StateDirectory(scope))
    if running is not None:
        running.Stop()
    shutil.rmtree(process.StateDirectory(scope), ignore_errors=True)


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
        bundle = []
        if args.interactive:
            install = ["cmake", "--install", str(args.build_dir), "--component", "realtime_plane"]
            subprocess.run([*install, "--prefix", str(root / "realtime-plane")], check=True, capture_output=True)
            bundle = ["--realtime-plane-dir", str(root / "realtime-plane")]
        subprocess.run(
            [
                sys.executable,
                str(args.package_script),
                "--extension",
                str(args.extension_dir.resolve()),
                "--library",
                str(args.library),
                "--wheel-dir",
                str(args.wheel_dir),
                *bundle,
                "--output",
                str(root / "flexible_drawing.zip"),
            ],
            check=True,
            capture_output=True,
        )
        environment = {
            **os.environ,
            "BLENDER_USER_CONFIG": str(root / "config"),
            "BLENDER_USER_SCRIPTS": str(root / "scripts"),
            "BLENDER_USER_EXTENSIONS": str(root / "extensions"),
            "BLENDER_USER_DATAFILES": str(root / "datafiles"),
            "FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE": scope,
        }
        environment.pop("FLEXIBLE_DRAWING_PROTOCOL_DIR", None)  # the package carries its own profile
        if args.peer is not None:
            standIn = [sys.executable, str(HERE / "realtime_plane_stand_in.py"), "--peer", str(args.peer)]
            environment["FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND"] = shlex.join(standIn)
        installed = subprocess.run(
            [
                str(args.blender),
                "--background",
                "--factory-startup",
                "--command",
                "extension",
                "install-file",
                "-r",
                "user_default",
                "-e",
                str(root / "flexible_drawing.zip"),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if installed.returncode != 0:
            print(installed.stdout + installed.stderr, file=sys.stderr)
            return installed.returncode or 1
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
                    "bl_ext.user_default.flexible_drawing",
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        finally:
            _stopLeftovers(root / "extensions/user_default/flexible_drawing", scope)
    output = completed.stdout + completed.stderr
    if completed.returncode != 0 or MARKER not in output:
        print(output, file=sys.stderr)
        print(f"FAIL: Blender exited with {completed.returncode} before {MARKER}", file=sys.stderr)
        return 1
    print(f"{MARKER} ({'real Realtime Plane, with a window' if args.interactive else 'stand-in, background'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
