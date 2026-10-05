"""Inside Blender: launch the Realtime Plane, control it while a stroke is drawn, and time the control.

Run by `test_realtime_plane_latency.py` as
``blender --background --python blender_realtime_plane_latency_host.py -- ARGUMENTS``.

Blender starts the Realtime Plane through the extension's own link, so the process is launched and
controlled by Blender exactly as a person's canvas is. The host turn runs at a Blender timer's 60 Hz.
Every quarter second it asks for another brush hardness and times how long the Realtime Plane takes
to report it in effect: that is control to activation, as a host sees it.

With `--stall`, the host stops taking turns while the stroke is drawn, the way a Blender busy with a
long operation would. The Realtime Plane must paint at the same speed anyway.

The script writes `ready` beside `--output` once a session is open, waits for `finish` to appear
there, stops the Realtime Plane, and writes its timings to `--output` as JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import types

OWNER = "presentation.tool_ui"
SET_HARDNESS = "pressure_brush.set_hardness"
HARDNESS = "pressure_brush.hardness"
HOST_TURN_S = 1.0 / 60.0
REQUEST_EVERY_S = 0.25
TIMEOUT_S = 30.0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--packages", type=Path, required=True, help="the extracted iceoryx2 wheels")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stall", action="store_true")
    parser.add_argument(
        "--program", nargs=argparse.REMAINDER, required=True, help="the Realtime Plane command line; last"
    )
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def main() -> None:
    arguments = _arguments()
    sys.path.insert(0, str(arguments.packages))
    root = types.ModuleType("flexible_drawing")
    root.__path__ = [str(arguments.extension_dir)]
    sys.modules["flexible_drawing"] = root
    import flexible_drawing.realtime_plane.link as link_module
    import flexible_drawing.realtime_plane.process as process

    link_module.StateDirectory = lambda _scope: arguments.state_dir
    link = link_module.RealtimePlaneLink(lambda: process.Program(tuple(arguments.program)), arguments.scope)
    link.Open()
    started = time.monotonic()
    while link.State is not link_module.LinkState.CONNECTED or link.Effective(OWNER, HARDNESS) is None:
        if time.monotonic() - started > TIMEOUT_S:
            raise TimeoutError(f"no session with the Realtime Plane: {link.Message}")
        link.Advance()
        time.sleep(HOST_TURN_S)

    directory = arguments.output.parent
    (directory / "ready").touch()
    controls: list[float] = []
    requested: tuple[float, float] | None = None  # value, when it was asked for
    nextRequest = time.monotonic()
    hardness = 0.5
    while not (directory / "finish").exists():
        if arguments.stall:
            time.sleep(HOST_TURN_S)  # a Blender that takes no host turn while the stroke is drawn
            continue
        now = time.monotonic()
        if requested is None and now >= nextRequest:
            hardness = 0.9 if hardness < 0.7 else 0.5
            if link.Request(OWNER, SET_HARDNESS, hardness):
                requested = (hardness, now)
        link.Advance()
        if requested is not None and link.Pending(OWNER, SET_HARDNESS) is None:
            if link.Effective(OWNER, HARDNESS) == requested[0]:
                controls.append(time.monotonic() - requested[1])
            requested = None
            nextRequest = time.monotonic() + REQUEST_EVERY_S
        time.sleep(HOST_TURN_S)

    pid = link.Process.Pid
    link.Stop()  # SIGTERM: the Realtime Plane ends its loop and writes its latency report
    arguments.output.write_text(
        json.dumps({"realtime_plane_pid": pid, "control_to_activation_s": controls}), encoding="utf-8"
    )
    print("FLEXIBLE_DRAWING_LATENCY_HOST_OK", flush=True)


main()
