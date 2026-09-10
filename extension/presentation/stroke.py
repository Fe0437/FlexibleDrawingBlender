"""Capture one freehand stroke in the viewport and hand it to the scene's receiver.

Blender delivers pointer input one event at a time, and crossing into the native engine costs more
than reading an event does. So this operator does not submit as it reads. It collects a run of
events and submits the whole run at once, on the boundary Blender itself provides: a fast tablet's
extra positions arrive as `INBETWEEN_MOUSEMOVE` events followed by the `MOUSEMOVE` they lead up to,
so the `MOUSEMOVE` ends a run and is where the batch is sent.

Everything below the event loop is `host.input_source`, which has no `bpy` in it and is tested
without Blender. This module is the Blender half: which region the pointer is in, when a stroke
starts and stops, and where the result is shown.

The tool and its operator exist only when Blender is hosting an in-process receiver. The Realtime
Plane owns its own native input and never receives pen events from Blender.
"""

from __future__ import annotations

import logging
import time

import bpy

from ..host import document_binding, receiver_binding
from ..host.input import MOTION_EVENT_ORIGINS, HostEventFromPointer
from ..host.input_source import InputSourceOnBlender
from ..host.viewport import IMAGE_EDITOR_SPACE_TYPE, CanvasExtent, ImageEditorRegionToCanvas
from . import Engine, InProcessReceiverSelected

_logger = logging.getLogger("flexible_drawing")

#: Provisional: the engine does not report a canvas size, so the host has to pick the extent it
#: measures pointer positions against. When the engine reports the extent, it comes from the bound
#: document instead. Nothing may treat this number as the canvas's real size.
_PROVISIONAL_CANVAS_EXTENT = CanvasExtent(Width=1024.0, Height=1024.0)

# One contact identity per stroke, so a run left over from a stroke that has ended is refused by the
# receiver rather than appended to the next one.
_nextContact = 1


def _takeContact() -> int:
    global _nextContact
    contact = _nextContact
    _nextContact += 1
    return contact


class PaintStrokeOperator(bpy.types.Operator):
    """Draw one stroke: runs while the pointer is down and ends when it is released."""

    bl_idname = "flexible_drawing.stroke_paint"
    bl_label = "Paint Flexible Drawing Stroke"
    #: Registered only when Blender hosts an in-process receiver; see `presentation/__init__.py`.
    RequiresInProcessReceiver = True

    @classmethod
    def poll(cls, context: object) -> bool:
        area = getattr(context, "area", None)
        return (
            InProcessReceiverSelected()
            and Engine() is not None
            and context.scene is not None
            and document_binding.Read(context.scene) is not None
            and area is not None
            and area.type == IMAGE_EDITOR_SPACE_TYPE
        )

    def invoke(self, context: object, event: object) -> set[str]:
        # The region is taken once, here, rather than read from the context on every event: the
        # pointer may leave the editor mid-stroke, and the stroke still belongs to where it started.
        self._region = context.region
        engine = Engine()
        receiverId = receiver_binding.Bind(engine, context.scene)
        self._source = InputSourceOnBlender(
            engine,
            receiverId,
            contactId=_takeContact(),
            maximumBatchSamples=receiver_binding.MAXIMUM_BATCH_SAMPLES,
        )
        self._source.Begin()
        # The press is a measured position, and the only sample a stroke that never moves will have.
        self._collect(event, "MEASURED")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context: object, event: object) -> set[str]:
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return self._cancel(context)
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return self._finish(context)

        origin = MOTION_EVENT_ORIGINS.get(event.type)
        if origin is None:
            # Something else entirely, such as a modifier key. Nothing to record, and not ours.
            return {"PASS_THROUGH"}
        self._collect(event, origin)
        if origin == "MEASURED":
            # Blender sends a run's coalesced positions first and the measured one last, so the run
            # is complete and goes to the engine as one call.
            self._source.Submit()
        return {"RUNNING_MODAL"}

    def _collect(self, event: object, origin: str) -> None:
        """Record one event, in canvas units, without calling the engine."""
        position = ImageEditorRegionToCanvas(
            self._region, event.mouse_region_x, event.mouse_region_y, _PROVISIONAL_CANVAS_EXTENT
        )
        self._source.Collect(
            HostEventFromPointer(event, position, self._source.NextSequence(), time.perf_counter_ns(), origin)
        )

    def _publish(self, context: object) -> None:
        """Put the latest receiver result where the sidebar reads it, and redraw to show it."""
        scene = context.scene
        snapshot = self._source.Snapshot
        scene["flexible_drawing_stroke_sample_count"] = self._source.Sequence
        if snapshot is not None:
            scene["flexible_drawing_receiver_revision"] = snapshot.Revision
            scene["flexible_drawing_committed_sequence"] = snapshot.CommittedSequence
        if context.area is not None:
            context.area.tag_redraw()

    def _finish(self, context: object) -> set[str]:
        dropped = self._source.Finish()
        self._publish(context)
        _logger.info(
            "[blender] stroke finished; samples=%d unsent=%d revision=%s",
            self._source.Sequence,
            dropped,
            None if self._source.Snapshot is None else self._source.Snapshot.Revision,
        )
        return {"FINISHED"}

    def _cancel(self, context: object) -> set[str]:
        # Nothing already committed can be taken back here; only what was never sent is dropped,
        # along with whatever the receiver was holding as provisional.
        dropped = self._source.Cancel()
        self._publish(context)
        _logger.info("[blender] stroke cancelled; samples=%d unsent=%d", self._source.Sequence, dropped)
        return {"CANCELLED"}


class PaintTool(bpy.types.WorkSpaceTool):
    """The toolbar entry that makes dragging in the Image Editor draw.

    A tool rather than a plain keymap entry. A keymap on the left button would take the pointer away
    from Blender's own Image Editor for as long as the add-on is enabled; a tool takes it only while
    the user has chosen to draw.
    """

    bl_space_type = IMAGE_EDITOR_SPACE_TYPE
    bl_context_mode = None
    bl_idname = "flexible_drawing.paint"
    bl_label = "Flexible Drawing"
    bl_description = "Draw a Flexible Drawing stroke"
    bl_icon = "ops.gpencil.draw"
    bl_keymap = ((PaintStrokeOperator.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, None),)
    #: Registered only when Blender hosts an in-process receiver; see `presentation/__init__.py`.
    RequiresInProcessReceiver = True
