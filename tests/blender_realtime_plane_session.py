"""Inside Blender: open the canvas, change a setting through the projected UI, reattach, and stop.

Run by `test_blender_realtime_plane.py` as
``blender [--background] --python blender_realtime_plane_session.py -- --module M``.
The Realtime Plane is whatever the add-on resolves: the stand-in a background run names in
`FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND`, or the bundled one in an interactive run.

Everything goes through what a person uses: the "Open Canvas" and "Stop Canvas" operators, and the
properties Blender made from the engine's UI schema, found by their labels. In the background there
is no event loop, so the script runs the add-on's timer turn itself; with a window, Blender's own
timer runs it and the script only watches. The result is one line, `FLEXIBLE_DRAWING_REALTIME_PLANE_OK`,
or an exception.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
import importlib
import os
import sys
import time
import types

import bpy

TIMEOUT_S = 30.0
OWNER = "presentation.tool_ui"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


arguments = _arguments()
flexible_drawing = importlib.import_module(arguments.module)
presentation = importlib.import_module(f"{arguments.module}.presentation")
realtime_plane = importlib.import_module(f"{arguments.module}.presentation.realtime_plane")
LinkState = importlib.import_module(f"{arguments.module}.realtime_plane.link").LinkState


def _property(label: str) -> str:
    """The projected property a person sees under `label`."""
    values = bpy.context.window_manager.flexible_drawing_ui
    for found in values.bl_rna.properties:
        if found.name == label:
            return found.identifier
    raise AssertionError(f"no projected control is labelled {label}")


def _link() -> object:
    link = presentation.RealtimePlane()
    assert link is not None, "the add-on lent no Realtime Plane link"
    return link


def _connected() -> bool:
    link = _link()
    return link.State is LinkState.CONNECTED and link.Effective(OWNER, "pressure_brush.hardness") is not None


class _RecordingLayout:
    """The labels a registered Blender panel asks Blender to draw."""

    def __init__(self) -> None:
        self.Labels: list[str] = []
        self.enabled = True

    def row(self) -> _RecordingLayout:
        return self

    def box(self) -> _RecordingLayout:
        return self

    def label(self, *, text: str, icon: str | None = None) -> None:
        self.Labels.append(text)

    def prop(self, _values: object, _property: str, *, text: str) -> None:
        return None

    def operator(self, _identifier: str, *, text: str) -> object:
        return types.SimpleNamespace()


def _activeToolLabels() -> list[str]:
    """Draw the panel Blender registered, and return what a person can read in it."""
    layout = _RecordingLayout()
    panel = types.SimpleNamespace(layout=layout)
    bpy.types.FD_PT_ui_1.draw(panel, bpy.context)
    return layout.Labels


def _steps() -> Iterator[tuple[str, Callable[[], bool]]]:
    """The conversation, as a person has it; each step yields what it waits for."""
    assert hasattr(bpy.types, "FD_PT_ui_0"), "the engine's UI was not projected into a panel"
    assert bpy.ops.flexible_drawing.canvas_open() == {"FINISHED"}
    yield "a session with the canvas", _connected
    pid = _link().Process.Pid
    assert "Effective freehand.pressure_brush" in _activeToolLabels()

    hardness = _property("Hardness")
    values = bpy.context.window_manager.flexible_drawing_ui
    setattr(values, hardness, 0.8)  # Blender calls the property's update, which requests the action
    assert _link().Pending(OWNER, "pressure_brush.set_hardness") == 0.8, "the change was not requested"
    assert any(label.startswith("Pending 0.8; in effect ") for label in _activeToolLabels())
    yield "the hardness to take effect", lambda: _link().Pending(OWNER, "pressure_brush.set_hardness") is None
    assert _link().Effective(OWNER, "pressure_brush.hardness") == 0.8
    assert abs(getattr(values, hardness) - 0.8) < 1e-6, "the widget does not show the value in effect"

    # A tool is adopted when the pen next touches the canvas. The stand-in's fake pen keeps drawing,
    # so the tool changes; nobody touches the real Realtime Plane here, so the choice stays pending.
    setattr(values, _property("Active Tool"), "freehand.pen")
    assert "Pending freehand.pen; in effect freehand.pressure_brush" in _activeToolLabels()
    if bpy.app.background:
        yield "the pen to become the tool", lambda: _link().Effective(OWNER, "active_tool") == "freehand.pen"
    else:
        settled = time.monotonic() + 2.0
        yield "the choice to travel", lambda: time.monotonic() > settled
        assert _link().Available, f"the session dropped: {_link().Message}"
        assert _link().Pending(OWNER, "select_tool") == "freehand.pen", "the choice was lost"

    # Disabling the add-on lets go of the canvas; enabling it again finds the same one.
    for _ in range(3):
        flexible_drawing.unregister()
        flexible_drawing.register()
        yield "the canvas to be found again", _connected
        assert _link().Process.Pid == pid, "a second Realtime Plane was started"

    assert bpy.ops.flexible_drawing.canvas_stop() == {"FINISHED"}
    assert _link().State is LinkState.STOPPED
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "Stop Canvas left the Realtime Plane running"
    flexible_drawing.unregister()
    print("FLEXIBLE_DRAWING_REALTIME_PLANE_OK", flush=True)


def _runInBackground() -> None:
    for what, condition in _steps():
        started = time.monotonic()
        while not condition():
            if time.monotonic() - started > TIMEOUT_S:
                raise TimeoutError(f"timed out waiting for {what}: {_link().Message}")
            realtime_plane._tick()  # the turn Blender's timer would run
            time.sleep(1.0 / 60.0)


def _runWithWindow() -> None:
    steps = _steps()
    waiting: list[tuple[str, Callable[[], bool], float]] = []

    def _watch() -> float | None:
        try:
            if waiting:
                what, condition, started = waiting[0]
                if not condition():
                    if time.monotonic() - started > TIMEOUT_S:
                        raise TimeoutError(f"timed out waiting for {what}: {_link().Message}")
                    return 0.05
                waiting.clear()
            what, condition = next(steps)
            waiting.append((what, condition, time.monotonic()))
            return 0.05
        except StopIteration:
            bpy.ops.wm.quit_blender()
        except Exception:
            import traceback

            traceback.print_exc()
            os._exit(1)
        return None

    bpy.app.timers.register(_watch, first_interval=1.0)


if bpy.app.background:
    _runInBackground()
else:
    _runWithWindow()
