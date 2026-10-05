"""Bind the canvas image into Blender materials, by identity, so the binding outlives the pixels.

A material that shows the canvas holds an image texture node marked with the canvas surface and the
drawing document it belongs to. The mark is the binding: it is all that a file save keeps. The
pixels are a derived copy, so when the canvas image is deleted, or comes back from a reopened file
without its pixels, the image is made again and `Restore` puts it back into every marked node.

Like `document_binding`, this module receives the Blender data it works on instead of importing
Blender, so what owns the material stays the caller's decision.

```python
node = canvas_binding.Bind(material, image, surface=1, document=7)
canvas_binding.Restore(bpy.data.materials, image, surface=1)  # after the image was made again
```
"""

from __future__ import annotations

from collections.abc import Iterable

#: Custom property naming the canvas surface, on the canvas image and on every node bound to it.
SURFACE = "flexible_drawing_surface"
#: Custom property naming the drawing document a bound node belongs to.
DOCUMENT = "flexible_drawing_document_id"
#: Name and label of the image texture node that shows the canvas.
NODE_NAME = "Flexible Drawing Canvas"


def SurfaceKey(surface: int) -> str:
    """How a surface identity is stored: as text, because an ID property integer has only 32 bits."""
    return str(surface)


def BoundNodes(material: object, surface: int) -> list[object]:
    """The image texture nodes of `material` bound to `surface`."""
    if material is None or material.node_tree is None:
        return []
    key = SurfaceKey(surface)
    nodes = material.node_tree.nodes
    return [node for node in nodes if node.bl_idname == "ShaderNodeTexImage" and node.get(SURFACE) == key]


def Bind(material: object, image: object, surface: int, document: int) -> object:
    """Show `image` in `material` through a node marked with `surface` and `document`; return it.

    Binding a material twice reuses its node. The node feeds the first Principled BSDF's base colour
    and alpha, so the canvas shows with the transparency it was painted with.
    """
    material.use_nodes = True
    tree = material.node_tree
    bound = BoundNodes(material, surface)
    node = bound[0] if bound else tree.nodes.new("ShaderNodeTexImage")
    node.name = node.label = NODE_NAME
    node[SURFACE] = SurfaceKey(surface)
    node[DOCUMENT] = document
    node.image = image
    shader = next((candidate for candidate in tree.nodes if candidate.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    if shader is not None:
        tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
        tree.links.new(node.outputs["Alpha"], shader.inputs["Alpha"])
        node.location = (shader.location[0] - 300.0, shader.location[1])
    return node


def Restore(materials: Iterable[object], image: object, surface: int) -> int:
    """Point every node bound to `surface` at `image` again; return how many changed."""
    restored = 0
    for material in materials:
        for node in BoundNodes(material, surface):
            if node.image != image:
                node.image = image
                restored += 1
    return restored
