"""The document buttons and the panel that holds them.

Class names here follow the usual project rules. What Blender cares about is `bl_idname`, not the
class name: an operator's must be `category.lower_snake_case`, and a panel's must contain `_PT_`
between a prefix and a suffix or Blender prints a warning when it registers. Those are strings, so
they carry Blender's requirements and the class names do not have to.

Nothing needs to list these classes anywhere. The package registers whatever it finds here; see
`presentation/__init__.py`.
"""

from __future__ import annotations

import logging

import bpy

from ..host import document_binding, receiver_binding
from . import Engine

# Every operator here has the same three parts: `poll` decides whether the button can be pressed,
# `execute` makes one engine call, and `document_binding` saves the result onto the scene. To add
# one, write those three and add a line to the panel's `draw` below.
_logger = logging.getLogger("flexible_drawing")


class CreateDocumentOperator(bpy.types.Operator):
    """Create a drawing document and bind its identity to the scene."""

    bl_idname = "flexible_drawing.document_create"
    bl_label = "Create Flexible Drawing"

    @classmethod
    def poll(cls, context: object) -> bool:
        return Engine() is not None and context.scene is not None and document_binding.Read(context.scene) is None

    def execute(self, context: object) -> set[str]:
        snapshot = Engine().Documents.Create("Drawing")
        document_binding.Bind(context.scene, snapshot)
        _logger.info("[blender] document created; id=%d revision=%d", snapshot.DocumentId, snapshot.Revision)
        return {"FINISHED"}


class InspectDocumentOperator(bpy.types.Operator):
    """Refresh the scene's stored identity from the engine's current view of the document."""

    bl_idname = "flexible_drawing.document_inspect"
    bl_label = "Inspect Flexible Drawing"

    @classmethod
    def poll(cls, context: object) -> bool:
        return Engine() is not None and context.scene is not None and document_binding.Read(context.scene) is not None

    def execute(self, context: object) -> set[str]:
        binding = document_binding.Read(context.scene)
        snapshot = Engine().Documents.Query(binding.DocumentId)
        document_binding.Bind(context.scene, snapshot)
        _logger.info("[blender] document inspected; id=%d revision=%d", snapshot.DocumentId, snapshot.Revision)
        return {"FINISHED"}


class CloseDocumentOperator(bpy.types.Operator):
    """Close the scene's document and remove its binding."""

    bl_idname = "flexible_drawing.document_close"
    bl_label = "Close Flexible Drawing"

    @classmethod
    def poll(cls, context: object) -> bool:
        return Engine() is not None and context.scene is not None and document_binding.Read(context.scene) is not None

    def execute(self, context: object) -> set[str]:
        binding = document_binding.Read(context.scene)
        engine = Engine()
        receiver_binding.Close(engine, context.scene)
        engine.Documents.Close(binding.DocumentId)
        document_binding.Clear(context.scene)
        _logger.info("[blender] document closed; id=%d", binding.DocumentId)
        return {"FINISHED"}


class DocumentPanel(bpy.types.Panel):
    """The Flexible Drawing panel in the scene properties, holding the buttons above."""

    bl_idname = "FD_PT_document"
    bl_label = "Flexible Drawing"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, _context: object) -> None:
        column = self.layout.column()
        # The operator's identifier rather than the class, because `presentation.viewport` imports
        # this module and importing it back would be a cycle.
        column.operator("flexible_drawing.viewport_open", text="Open 2D Canvas").SpaceType = "IMAGE_EDITOR"
        column.operator("flexible_drawing.viewport_open", text="Open 3D Viewport").SpaceType = "VIEW_3D"
        column.operator(CreateDocumentOperator.bl_idname)
        column.operator(InspectDocumentOperator.bl_idname)
        column.operator(CloseDocumentOperator.bl_idname)
