#!/usr/bin/env python3
"""Draw in the real Realtime Plane and check that Blender shows it, through a reopen and a restart.

The packaged extension, carrying the real Realtime Plane, is installed into a throwaway profile.
Strokes come from `drawing_input`: posted pointer events (`--input synthetic`, unattended, run by
CTest and `just blender-test`) or a person (`--input person`, `just blender-test BLENDER CONFIG person`).
Two Blender processes run `blender_canvas_session.py` one after the other:

1. the first opens the canvas; after a stroke, the image and every tile of it must hold exactly the
   pixels received, a render of the bound material must match the image, and during a long stroke
   the image must update without stalling; it saves the file and lets go of the Realtime Plane;
2. the second opens the saved file, finds the Realtime Plane still running, and must rebuild the
   image to the same hash with no stroke drawn, and once more after the image is deleted; then it
   stops the canvas.

`--output` keeps what was measured. The check skips (77) when synthetic input cannot be posted.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from drawing_input import INPUTS, DrawingInput
from packaged_blender import MODULE, Install, RealtimePlaneLog, RealtimePlanePid, StopLeftovers

HERE = Path(__file__).resolve().parent
SKIP = 77
TIMEOUT_S = 240.0


def _waitFor(path: Path, blender: subprocess.Popen) -> None:
    """Wait for Blender to ask for a stroke; fail if it ends or takes too long instead."""
    started = time.monotonic()
    while not path.exists():
        if blender.poll() is not None:
            raise RuntimeError(f"Blender ended before it asked for {path.stem}:\n{blender.communicate()[0]}")
        if time.monotonic() - started > TIMEOUT_S:
            blender.kill()
            raise TimeoutError(f"Blender never asked for {path.stem}")
        time.sleep(0.05)


def _blender(args: argparse.Namespace, environment: dict, exchange: Path, phase: str, *opening: str) -> object:
    return subprocess.Popen(
        [
            str(args.blender),
            "--background",
            *opening,
            "--python-exit-code",
            "1",
            "--python",
            str(HERE / "blender_canvas_session.py"),
            "--",
            "--module",
            MODULE,
            "--phase",
            phase,
            "--exchange",
            str(exchange),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _finish(blender: subprocess.Popen, phase: str) -> None:
    output, _ = blender.communicate(timeout=TIMEOUT_S)
    marker = f"FLEXIBLE_DRAWING_CANVAS_{phase.upper()}_OK"
    if blender.returncode != 0 or marker not in output:
        raise RuntimeError(f"Blender's {phase} phase failed ({blender.returncode}):\n{output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--package-script", type=Path, required=True)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True, help="the build to install the Realtime Plane from")
    parser.add_argument("--input", choices=INPUTS, default="synthetic")
    parser.add_argument("--device", default="", help="what drew, when a person did: a pen's model, or a mouse")
    parser.add_argument("--output", type=Path, help="where to keep what was measured, as JSON")
    parser.add_argument("--log", type=Path, help="a file to add what was measured to, one JSON line per run")
    parser.add_argument("--keep", type=Path, help="work in this directory and keep it: the saved file, the render")
    args = parser.parse_args()
    drawing = DrawingInput.Open(args.input, args.device)
    if drawing is None:
        print("SKIP: posted pointer events reach no window: grant Accessibility, unlock the screen")
        return SKIP

    scope = f"canvas-check-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="flexible-drawing-canvas-") as directory:
        root = Path(directory) if args.keep is None else args.keep.resolve()
        root.mkdir(parents=True, exist_ok=True)
        exchange = root / "exchange"
        exchange.mkdir(exist_ok=True)
        try:
            environment = Install(root, args, scope, buildDir=args.build_dir)
            first = _blender(args, environment, exchange, "first")
            _waitFor(exchange / "stroke.ready", first)
            window = RealtimePlanePid(root, scope)
            drawing.Draw(window, 2, 0.8, 0, "two short strokes across the canvas")
            (exchange / "stroke.drawn").touch()
            _waitFor(exchange / "long.ready", first)
            drawing.Draw(window, 1, 3.0, 1, "one long stroke, about three seconds", (exchange / "long.drawing").touch)
            (exchange / "long.drawn").touch()
            _finish(first, "first")
            # A new Blender, the saved file, and the Realtime Plane the first one left running.
            second = _blender(args, environment, exchange, "second", str(exchange / "canvas.blend"))
            _finish(second, "second")
            result = {
                "when": datetime.now().isoformat(timespec="seconds"),
                "input": drawing.Description,
                **json.loads((exchange / "result-first.json").read_text(encoding="utf-8")),
                **json.loads((exchange / "result-second.json").read_text(encoding="utf-8")),
            }
        except Exception:
            print(f"The Realtime Plane's log:\n{RealtimePlaneLog(root, scope)}", file=sys.stderr)
            raise
        finally:
            StopLeftovers(root, scope)
    text = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(result) + "\n")
    print(text)
    print("FLEXIBLE_DRAWING_CANVAS_IN_BLENDER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
