#!/usr/bin/env python3
"""Check the UI projected from the engine's schema, and the Realtime Plane's place in Blender.

Blender is the fake from `test_blender_plugin.py`; the engine describes a UI with one control of
every role; the Realtime Plane link is a fake that records requests and reports what a test says.
The projection must make a widget for every role and a panel for every surface and section without
naming any control, send each change through the control's action binding, show a request as
pending beside the value in effect, and take the effective value once the request applied. The add-on
must follow the link on a timer and let go of the Realtime Plane, not stop it, when it is disabled.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import types
from typing import ClassVar
import unittest
from unittest import mock

from test_blender_plugin import FakeBridge, RecordingLayout, fake_bpy

OWNER = "presentation.tool_ui"


class FakeLink:
    """A Realtime Plane link that records what the UI asks of it."""

    Label = "Realtime Plane (external canvas)"
    created: ClassVar[list[FakeLink]] = []

    def __init__(self, program: object, scope: str | None = None) -> None:
        self.Program = program
        self.Requests: list[tuple[str, str, object]] = []
        self.PendingValues: dict[tuple[str, str], object] = {}
        self.EffectiveValues: dict[tuple[str, str], object] = {(OWNER, "pressure_brush.hardness"): 0.35}
        self.State = self._states().CONNECTED
        self.Calls: list[str] = []
        self.Changed = False
        self.OpenError: OSError | None = None
        type(self).created.append(self)

    @staticmethod
    def _states() -> object:
        return importlib.import_module("flexible_drawing.realtime_plane.link").LinkState

    @property
    def Available(self) -> bool:
        return self.State is self._states().CONNECTED

    @property
    def UnavailableReason(self) -> str:
        if self.State is self._states().STOPPED:
            return f"Open {self.Label} to change these settings"
        return self.Message or f"Connecting to {self.Label}"

    def Request(self, owner: str, action: str, value: object) -> bool:
        self.Requests.append((owner, action, value))
        if value is None:
            return False
        self.PendingValues[(owner, action)] = value
        return True

    def Pending(self, owner: str, action: str) -> object:
        return self.PendingValues.get((owner, action))

    def Effective(self, owner: str, state: str) -> object:
        return self.EffectiveValues.get((owner, state))

    def Apply(self, action: str, state: str) -> None:
        """What a published tool state does: the request takes effect."""
        self.EffectiveValues[(OWNER, state)] = self.PendingValues.pop((OWNER, action))

    def Advance(self) -> bool:
        self.Calls.append("Advance")
        return self.Changed

    def Reattach(self) -> bool:
        self.Calls.append("Reattach")
        return False

    def Open(self) -> None:
        self.Calls.append("Open")
        if self.OpenError is not None:
            raise self.OpenError

    def Stop(self) -> None:
        self.Calls.append("Stop")

    def Detach(self) -> None:
        self.Calls.append("Detach")


class ProjectionTests(unittest.TestCase):
    extension: Path

    def setUp(self) -> None:
        FakeLink.created.clear()
        self.bpy = fake_bpy()
        patcher = mock.patch.dict(sys.modules, {"bpy": self.bpy})
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location(
            "flexible_drawing", self.extension / "__init__.py", submodule_search_locations=[str(self.extension)]
        )
        self.module = importlib.util.module_from_spec(spec)
        sys.modules["flexible_drawing"] = self.module
        spec.loader.exec_module(self.module)
        self.module.EngineBridge = FakeBridge
        self.module.RealtimePlaneLink = FakeLink
        self.module.register()
        self.addCleanup(self.module.unregister)
        self.link = FakeLink.created[-1]
        self.projection = importlib.import_module("flexible_drawing.presentation.ui_projection")
        self.registered = {getattr(found, "bl_idname", found.__name__): found for found in self.bpy.registered}
        self.values = self.registered["FD_UiValues"]
        # Blender would make this from the values group when it registers it.
        self.bpy.context.window_manager.flexible_drawing_ui = types.SimpleNamespace(
            control_3=0.35, control_4="freehand.pressure_brush", control_5=0, control_6=False, control_7=""
        )
        self.shown = self.bpy.context.window_manager.flexible_drawing_ui

    def _draw(self, identifier: str) -> RecordingLayout:
        panel = self.registered[identifier]()
        panel.layout = RecordingLayout()
        panel.draw(self.bpy.context)
        return panel.layout

    def _change(self, name: str, value: object) -> None:
        """What Blender does when a person edits a widget: set the value, then call its update."""
        setattr(self.shown, name, value)
        self.values.__annotations__[name]["update"](self.shown, self.bpy.context)

    def test_every_role_becomes_a_widget_and_every_container_a_panel(self) -> None:
        widgets = {name: (field["kind"], field["name"]) for name, field in self.values.__annotations__.items()}
        self.assertEqual(
            widgets,
            {
                "control_3": ("FloatProperty", "Hardness"),
                "control_4": ("EnumProperty", "Active Tool"),
                "control_5": ("IntProperty", "Spacing"),
                "control_6": ("BoolProperty", "Smoothing"),
                "control_7": ("StringProperty", "Name"),
            },
        )
        self.assertEqual(
            self.values.__annotations__["control_4"]["items"],
            (
                ("freehand.pressure_brush", "Pressure Brush", "freehand.pressure_brush"),
                ("freehand.pen", "Pen", "freehand.pen"),
            ),
        )
        surface, section = self.registered["FD_PT_ui_0"], self.registered["FD_PT_ui_1"]
        self.assertEqual((surface.bl_label, surface.bl_parent_id), ("Painting", "FD_PT_document"))
        self.assertEqual((section.bl_label, section.bl_parent_id), ("Active Tool", "FD_PT_ui_0"))
        self.assertNotIn("FD_PT_ui_2", self.registered, "a group is a box inside its panel, not a panel")
        order = [found.__name__ for found in self.bpy.registered]
        self.assertLess(order.index("FD_UiValues"), order.index("FD_PT_ui_0"))
        self.assertLess(order.index("FD_PT_ui_0"), order.index("FD_PT_ui_1"))
        preferences = self.registered["flexible_drawing"]
        self.assertIsInstance(
            preferences.__annotations__["RealtimePlaneExecutable"],
            dict,
            "Blender properties must not be postponed into string annotations",
        )
        self.assertIsInstance(self.projection.UiActionOperator.__annotations__["Element"], dict)

    def test_a_change_requests_the_action_and_shows_pending_then_effective(self) -> None:
        self._change("control_3", 0.8)
        self._change("control_5", 3)
        self._change("control_4", "freehand.pen")
        self.assertEqual(
            self.link.Requests,
            [
                (OWNER, "pressure_brush.set_hardness", 0.8),
                (OWNER, "pressure_brush.set_spacing", 3.0),  # every number travels as a real number
                (OWNER, "select_tool", "freehand.pen"),
            ],
        )
        section = self._draw("FD_PT_ui_1")
        self.assertIn("Settings", section.Labels)
        self.assertIn(("control_3", "Hardness", True), section.Properties)
        self.assertIn("Pending 0.8; in effect 0.35", section.Labels)
        # The Realtime Plane reports the request in effect; the widget keeps showing it.
        self.link.Apply("pressure_brush.set_hardness", "pressure_brush.hardness")
        self.projection.Refresh(self.bpy.context.window_manager)
        self.assertEqual(self.shown.control_3, 0.8)
        applied = self._draw("FD_PT_ui_1").Labels
        self.assertNotIn("Pending 0.8; in effect 0.35", applied)
        self.assertIn("Effective 0.8", applied)
        self.assertEqual(len(self.link.Requests), 3, "showing a value never requests it")

    def test_a_pending_request_is_not_overwritten_by_the_value_in_effect(self) -> None:
        self._change("control_3", 0.9)
        self.projection.Refresh(self.bpy.context.window_manager)
        self.assertEqual(self.shown.control_3, 0.9)
        self.link.EffectiveValues[(OWNER, "pressure_brush.spacing")] = 7.0
        self.link.EffectiveValues[(OWNER, "active_tool")] = "freehand.pen"
        self.projection.Refresh(self.bpy.context.window_manager)
        self.assertEqual((self.shown.control_5, self.shown.control_4), (7, "freehand.pen"))
        self.assertIsInstance(self.shown.control_5, int, "Blender refuses a real number for a whole one")

    def test_the_surface_says_what_it_acts_on_and_waits_for_the_canvas(self) -> None:
        surface = self._draw("FD_PT_ui_0")
        self.assertEqual(surface.Labels[0], "Acts on: Realtime Plane (external canvas)")
        self.assertIn("flexible_drawing.ui_action [Clear]", surface.Operators)
        self.link.State = self.link._states().STOPPED
        closed = self._draw("FD_PT_ui_0")
        self.assertEqual(closed.Labels[0], "Open Realtime Plane (external canvas) to change these settings")
        self.assertTrue(all(not enabled for _name, _text, enabled in self._draw("FD_PT_ui_1").Properties))
        self.assertFalse(self.projection.UiActionOperator.poll(self.bpy.context))
        self.link.State = self.link._states().CONNECTING
        self.link.Message = "could not reach the Realtime Plane: No module named 'iceoryx2'"
        waiting = self._draw("FD_PT_ui_0")
        self.assertEqual(waiting.Labels[0], self.link.Message)

    def test_a_command_the_canvas_does_not_take_is_reported(self) -> None:
        operator = self.projection.UiActionOperator()
        operator.Element = 8
        reports: list[tuple[set[str], str]] = []
        operator.report = lambda kind, message: reports.append((kind, message))
        self.assertEqual(operator.execute(self.bpy.context), {"CANCELLED"})
        self.assertEqual(self.link.Requests[-1], (OWNER, "canvas.clear", None))
        self.assertEqual(reports, [({"WARNING"}, "Realtime Plane (external canvas) does not take Clear yet")])

    def test_the_add_on_follows_the_link_and_lets_go_of_it(self) -> None:
        realtimePlane = importlib.import_module("flexible_drawing.presentation.realtime_plane")
        self.assertEqual(self.link.Calls, ["Reattach"], "a running Realtime Plane is found at startup")
        ((tick, _interval),) = self.bpy.timerCallbacks
        self.link.Changed = True
        self.link.EffectiveValues[(OWNER, "pressure_brush.hardness")] = 0.6
        self.assertEqual(tick(), realtimePlane.CONNECTED_INTERVAL)
        self.assertEqual(self.shown.control_3, 0.6, "a turn that changed something refreshes the UI")
        self.link.State = self.link._states().STOPPED
        self.assertEqual(tick(), realtimePlane.WAITING_INTERVAL)

        opened = realtimePlane.OpenCanvasOperator()
        self.assertTrue(realtimePlane.OpenCanvasOperator.poll(self.bpy.context))
        self.assertEqual(opened.execute(self.bpy.context), {"FINISHED"})
        self.link.OpenError = FileNotFoundError("no Realtime Plane here")
        reports: list[str] = []
        opened.report = lambda _kind, message: reports.append(message)
        self.assertEqual(opened.execute(self.bpy.context), {"CANCELLED"})
        self.assertEqual(reports, ["Could not start the Realtime Plane: no Realtime Plane here"])
        self.link.State = self.link._states().CONNECTING
        self.assertTrue(realtimePlane.StopCanvasOperator.poll(self.bpy.context))

        self.module.unregister()
        self.assertEqual(self.bpy.timerCallbacks, [])
        self.assertEqual(self.link.Calls[-1], "Detach")
        self.assertNotIn("Stop", self.link.Calls, "disabling the add-on never ends the Realtime Plane")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-source-dir", type=Path, required=True)
    parser.add_argument("--extension-dir", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    os.environ["FLEXIBLE_DRAWING_PROTOCOL_DIR"] = str(
        args.project_source_dir / "apps/application/ipc/realtime_plane_protocol"
    )
    os.environ["FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE"] = f"ui-test-{os.getpid()}"
    ProjectionTests.extension = args.extension_dir.resolve()
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
