"""The Flexible Drawing sidebar, in each Blender editor that can host the viewport.

Blender takes one `bl_space_type` per panel, so a sidebar shown in two editors is two registered
classes. Only that one line differs, so the shared part is a plain mixin: it is not a `bpy.types.Panel`
subclass, which is what keeps the package registrar from registering the shared half on its own.

Blender-area changes stay in `host.viewport`, and drawing the document's canvas remains a separate
presentation job.
"""

from __future__ import annotations

import bpy

from ..host import document_binding
from ..host.viewport import (
    IMAGE_EDITOR_SPACE_TYPE,
    VIEW_3D_SPACE_TYPE,
    OpenViewportWindow,
    RevealViewportSidebar,
)
from . import Engine
from .document import CloseDocumentOperator, CreateDocumentOperator, InspectDocumentOperator

# Blender can only select a sidebar tab after it has drawn that sidebar once, and a new window
# reaches its first draw a few frames after the operator returns. Retrying for about three seconds
# covers that with room to spare, and gives up rather than retrying forever if the tab never appears.
_REVEAL_RETRY_INTERVAL = 0.05
_REVEAL_ATTEMPTS = 60


def _scheduleSidebarReveal(area: object) -> None:
    attemptsRemaining = _REVEAL_ATTEMPTS

    def _reveal() -> float | None:
        nonlocal attemptsRemaining
        attemptsRemaining -= 1
        try:
            if RevealViewportSidebar(area) or attemptsRemaining == 0:
                return None
        except ReferenceError:
            # The user closed the window before it finished opening.
            return None
        return _REVEAL_RETRY_INTERVAL

    bpy.app.timers.register(_reveal, first_interval=0.0)


class OpenViewportOperator(bpy.types.Operator):
    """Open the Flexible Drawing viewport in a new Blender window."""

    bl_idname = "flexible_drawing.viewport_open"
    bl_label = "Open Flexible Drawing Viewport"

    # Which editor to open is the caller's choice rather than two near-identical operators, so the
    # panel and a keymap select it the same way.
    SpaceType: bpy.props.EnumProperty(
        name="Editor",
        description="Which Blender editor hosts the Flexible Drawing canvas",
        items=(
            (
                IMAGE_EDITOR_SPACE_TYPE,
                "Image Editor",
                "Show the canvas flat, where a pointer position needs no projection",
            ),
            (VIEW_3D_SPACE_TYPE, "3D Viewport", "Show the canvas placed in the scene"),
        ),
        default=IMAGE_EDITOR_SPACE_TYPE,
    )

    @classmethod
    def poll(cls, context: object) -> bool:
        return Engine() is not None and getattr(context, "area", None) is not None

    def execute(self, context: object) -> set[str]:
        area = OpenViewportWindow(bpy, self.SpaceType)
        if area is None:
            self.report({"ERROR"}, f"Blender did not open a {self.SpaceType} window")
            return {"CANCELLED"}
        # The new window has not been drawn yet, so its sidebar has no tab to select. Ask once in
        # case Blender is ahead of us, then keep asking on a timer.
        if not RevealViewportSidebar(area):
            _scheduleSidebarReveal(area)
        return {"FINISHED"}


class ViewportSidebar:
    """What the sidebar shows, shared by every editor that hosts it.

    Not a `bpy.types.Panel` subclass on purpose: the package registrar registers Blender classes it
    finds, and this half must not be registered on its own.
    """

    bl_label = "Flexible Drawing"
    bl_region_type = "UI"
    bl_category = "Flexible Drawing"

    def draw(self, context: object) -> None:
        column = self.layout.column()
        scene = context.scene
        binding = document_binding.Read(scene) if scene is not None else None
        if binding is None:
            column.label(text="No document is bound to this scene")
        else:
            column.label(text=f"Document {binding.DocumentId}")
            column.label(text=f"Revision {binding.Revision}")
            column.label(text=f"Layers {binding.LayerCount}")
            # A receiver revision, not a tile count: the engine reports what it accepted, and
            # where that is drawn is the receiver's presentation provider's business.
            revision = scene.get("flexible_drawing_receiver_revision")
            if revision is not None:
                column.label(text=f"Canvas revision {revision}")
            samples = scene.get("flexible_drawing_stroke_sample_count")
            if samples is not None:
                column.label(text=f"Stroke samples {samples}")

        column.operator(CreateDocumentOperator.bl_idname)
        column.operator(InspectDocumentOperator.bl_idname)
        column.operator(CloseDocumentOperator.bl_idname)


class ImageEditorSidebarPanel(ViewportSidebar, bpy.types.Panel):
    """The sidebar in Blender's Image Editor, where the canvas is shown flat."""

    bl_idname = "FD_PT_viewport_image_editor"
    bl_space_type = IMAGE_EDITOR_SPACE_TYPE


class View3DSidebarPanel(ViewportSidebar, bpy.types.Panel):
    """The sidebar in Blender's 3D View, where the canvas is placed in the scene."""

    bl_idname = "FD_PT_viewport_view_3d"
    bl_space_type = VIEW_3D_SPACE_TYPE
