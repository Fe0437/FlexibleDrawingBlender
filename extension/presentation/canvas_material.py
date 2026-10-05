"""The buttons that show the canvas image on an object, through its material.

A person selects an object and presses "Use Canvas in Material". The object's active material, or a
new one if it has none, gets an image texture node bound to the canvas surface and the scene's
drawing document. Only that binding is kept with the file; the pixels always come from the
Realtime Plane, so the material shows the canvas again after the file is reopened or the image is
deleted (see `canvas_image`).

"Add Canvas Plane" does all of it at once: a plane with the canvas's proportions, its material
bound, and the 3D views switched to Material Preview so the canvas shows on it.
"""

from __future__ import annotations

import bpy

from ..host import canvas_binding, document_binding
from . import Engine, canvas_image

#: The material made for an object that has none.
MATERIAL_NAME = "Flexible Drawing Canvas"


class UseCanvasInMaterialOperator(bpy.types.Operator):
    """Show the canvas on the active object, through an image texture in its material"""

    bl_idname = "flexible_drawing.canvas_material"
    bl_label = "Use Canvas in Material"

    @classmethod
    def poll(cls, context: object) -> bool:
        target = context.object
        return (
            target is not None
            and hasattr(target.data, "materials")
            and context.scene is not None
            and document_binding.Read(context.scene) is not None
            and canvas_image.CanvasImage() is not None
        )

    def execute(self, context: object) -> set[str]:
        target = context.object
        image = canvas_image.CanvasImage()
        material = target.active_material
        if material is None:
            material = bpy.data.materials.new(MATERIAL_NAME)
            target.data.materials.append(material)
            target.active_material_index = len(target.data.materials) - 1
        document = document_binding.Read(context.scene).DocumentId
        canvas_binding.Bind(material, image, int(image[canvas_binding.SURFACE]), document)
        self.report({"INFO"}, f"{material.name} shows {image.name}")
        return {"FINISHED"}


def _canvasPlane(context: object, width: int, height: int) -> object:
    """A new plane with the canvas's proportions and UVs covering it once, active and selected.

    Made from data rather than with Blender's add-plane operator: called from the Properties
    editor, that operator leaves this operator's context without the new object.
    """
    half = width / height
    mesh = bpy.data.meshes.new(MATERIAL_NAME)
    mesh.from_pydata([(-half, -1.0, 0.0), (half, -1.0, 0.0), (half, 1.0, 0.0), (-half, 1.0, 0.0)], [], [(0, 1, 2, 3)])
    uvs = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(mesh.polygons[0].loop_indices, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), strict=True):
        uvs.data[loop].uv = uv
    mesh.update()
    plane = bpy.data.objects.new(MATERIAL_NAME, mesh)
    plane.location = context.scene.cursor.location
    context.collection.objects.link(plane)
    for selected in context.selected_objects:
        selected.select_set(False)
    plane.select_set(True)
    context.view_layer.objects.active = plane
    return plane


class AddCanvasPlaneOperator(bpy.types.Operator):
    """Add a plane that shows the canvas, and show materials in the 3D views"""

    bl_idname = "flexible_drawing.canvas_plane"
    bl_label = "Add Canvas Plane"

    @classmethod
    def poll(cls, context: object) -> bool:
        return Engine() is not None and context.scene is not None and canvas_image.CanvasImage() is not None

    def execute(self, context: object) -> set[str]:
        image = canvas_image.CanvasImage()
        if document_binding.Read(context.scene) is None:
            # The binding belongs to a document; a scene without one gets one, as Create would.
            document_binding.Bind(context.scene, Engine().Documents.Create("Drawing"))
        plane = _canvasPlane(context, *image.size)
        material = bpy.data.materials.new(MATERIAL_NAME)
        plane.data.materials.append(material)
        document = document_binding.Read(context.scene).DocumentId
        canvas_binding.Bind(material, image, int(image[canvas_binding.SURFACE]), document)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces.active.shading.type = "MATERIAL"
        self.report({"INFO"}, f"{plane.name} shows {image.name}")
        return {"FINISHED"}
