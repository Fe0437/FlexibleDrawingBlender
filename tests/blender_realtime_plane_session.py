"""Inside Blender: open the canvas, see it as an image, change a setting through the projected UI,
reattach, and stop.

Run by `test_blender_realtime_plane.py` as
``blender [--background] --python blender_realtime_plane_session.py -- --module M``.
The Realtime Plane is whatever the add-on resolves: the stand-in a background run names in
`FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND`, or the bundled one in an interactive run.

Everything goes through what a person uses: the "Open Canvas" and "Stop Canvas" operators, and the
properties Blender made from the engine's UI schema, found by their labels. In the background there
is no event loop, so the script runs the add-on's timer turn itself; with a window, Blender's own
timer runs it and the script only watches. Where the stand-in's fake pen paints, the canvas image
must hold exactly the pixels the session received, stay one image across reattaching, and survive
the add-on being disabled. The result is one line, `FLEXIBLE_DRAWING_REALTIME_PLANE_OK`,
or an exception.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
import importlib
import os
import sys
import tempfile
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
canvas_image = importlib.import_module(f"{arguments.module}.presentation.canvas_image")
canvas_binding = importlib.import_module(f"{arguments.module}.host.canvas_binding")


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


def _canvasImages() -> list[object]:
    """Every image that shows a Realtime Plane surface."""
    return [image for image in bpy.data.images if canvas_image.SURFACE_KEY in image]


def _imageShowsTheCanvas() -> bool:
    """Whether the canvas image holds, tile for tile, the pixels the session received."""
    mirror = _link().Session.Mirror
    images = _canvasImages()
    if mirror.Image is None or len(images) != 1 or not mirror.Tiles:
        return False
    image = images[0]
    shape = mirror.Image
    if tuple(image.size) != (shape.Width, shape.Height):
        return False
    pixels = [0.0] * (shape.Width * shape.Height * 4)
    image.pixels.foreach_get(pixels)
    for (x, y), (_revision, data) in mirror.Tiles.items():
        sent = memoryview(data).cast("f")
        for row in range(shape.TileExtent):
            top = y * shape.TileExtent + row
            if top >= shape.Height:
                continue
            for column in range(shape.TileExtent):
                left = x * shape.TileExtent + column
                if left >= shape.Width:
                    continue
                shown = ((shape.Height - 1 - top) * shape.Width + left) * 4
                received = (row * shape.TileExtent + column) * 4
                if any(abs(pixels[shown + c] - sent[received + c]) > 1e-6 for c in range(4)):
                    return False
    return True


def _checkCanvasImage() -> None:
    """The image is the canvas: one image, float, premultiplied, linear, the canvas's size."""
    (image,) = _canvasImages()
    shape = _link().Session.Mirror.Image
    assert image.is_float and image.alpha_mode == "PREMUL", "the canvas image is not premultiplied float"
    assert image.colorspace_settings.name == canvas_image.COLOR_SPACE, image.colorspace_settings.name
    assert tuple(image.size) == (shape.Width, shape.Height), tuple(image.size)
    assert image[canvas_image.SURFACE_KEY] == str(shape.Surface)
    assert canvas_image.Status(_link()).startswith("Canvas image: revision"), canvas_image.Status(_link())


def _materialShowsTheCanvas(materialName: str, surface: int) -> Callable[[], bool]:
    """Whether the material's one bound node shows the canvas image, and that image shows the canvas."""

    def shows() -> bool:
        material = bpy.data.materials.get(materialName)
        nodes = canvas_binding.BoundNodes(material, surface)
        return len(nodes) == 1 and nodes[0].image in _canvasImages() and _imageShowsTheCanvas()

    return shows


def _materialSteps() -> Iterator[tuple[str, Callable[[], bool]]]:
    """Bind the canvas into a material, and keep it bound through what a person does to the scene."""
    if bpy.context.scene.get("flexible_drawing_document_id") is None:
        assert bpy.ops.flexible_drawing.document_create() == {"FINISHED"}
    bpy.ops.mesh.primitive_plane_add()
    plane = bpy.context.object
    assert bpy.ops.flexible_drawing.canvas_material() == {"FINISHED"}
    material = plane.active_material
    surface = int(_canvasImages()[0][canvas_image.SURFACE_KEY])
    (node,) = canvas_binding.BoundNodes(material, surface)
    shader = material.node_tree.nodes["Principled BSDF"]
    assert shader.inputs["Base Color"].links[0].from_node == node, "the canvas does not colour the material"
    assert shader.inputs["Alpha"].links[0].from_node == node, "the canvas alpha does not reach the material"
    assert node[canvas_binding.DOCUMENT] == bpy.context.scene["flexible_drawing_document_id"]
    assert bpy.ops.flexible_drawing.canvas_material() == {"FINISHED"}
    assert len(canvas_binding.BoundNodes(material, surface)) == 1, "binding twice added a node"
    shows = _materialShowsTheCanvas(material.name, surface)
    yield "the material to show the canvas", shows

    # Editing the mesh changes nothing the binding depends on, and the canvas keeps arriving.
    assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
    seen = _link().Session.Mirror.CanvasRevision

    def moved() -> bool:
        return _link().Session.Mirror.CanvasRevision > seen and shows()

    yield "the canvas to move while the mesh is edited", moved
    assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}

    # The object goes; the material and its binding stay for whoever uses them next.
    bpy.data.objects.remove(plane)
    yield "the canvas to keep arriving without the object", shows

    # The image is only a copy: deleted, it comes back with exactly the pixels received.
    bpy.data.images.remove(_canvasImages()[0])
    yield "the deleted canvas image to come back into the material", shows

    # One click: a plane with the canvas's proportions, its own material bound to the canvas. Pressed
    # in the Properties editor, the context has no object, as here.
    with bpy.context.temp_override(object=None, active_object=None):
        assert bpy.ops.flexible_drawing.canvas_plane() == {"FINISHED"}
    canvasPlane = bpy.context.view_layer.objects.active
    width, height = _canvasImages()[0].size
    proportion = canvasPlane.dimensions[0] / canvasPlane.dimensions[1]
    assert abs(proportion - width / height) < 1e-6, tuple(canvasPlane.dimensions)
    yield "the canvas plane to show the canvas", _materialShowsTheCanvas(canvasPlane.active_material.name, surface)

    # A saved file keeps the binding, not the pixels; reopened, the session fills the image again.
    path = os.path.join(tempfile.mkdtemp(prefix="flexible-drawing-canvas-"), "canvas.blend")
    assert bpy.ops.wm.save_as_mainfile(filepath=path) == {"FINISHED"}
    name = material.name
    assert bpy.ops.wm.open_mainfile(filepath=path) == {"FINISHED"}
    yield "the reopened file to show the canvas", _materialShowsTheCanvas(name, surface)


def _steps() -> Iterator[tuple[str, Callable[[], bool]]]:
    """The conversation, as a person has it; each step yields what it waits for."""
    assert hasattr(bpy.types, "FD_PT_ui_0"), "the engine's UI was not projected into a panel"
    assert bpy.ops.flexible_drawing.canvas_open() == {"FINISHED"}
    yield "a session with the canvas", _connected
    pid = _link().Process.Pid
    # The stand-in's fake pen paints, so its canvas reaches the image; nobody touches the real one.
    painted = bpy.app.background
    if painted:
        yield "the canvas image to show the canvas", _imageShowsTheCanvas
        _checkCanvasImage()
        yield from _materialSteps()
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
        # A new session rebuilds the same image from the whole canvas; it never adds another.
        if painted:
            yield "the canvas image to show the canvas again", _imageShowsTheCanvas
            assert len(_canvasImages()) == 1, "enabling the add-on again added a canvas image"

    assert bpy.ops.flexible_drawing.canvas_stop() == {"FINISHED"}
    assert _link().State is LinkState.STOPPED
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "Stop Canvas left the Realtime Plane running"
    flexible_drawing.unregister()
    assert not bpy.app.timers.is_registered(realtime_plane._tick), "unregistering left the timer running"
    assert len(_canvasImages()) == (1 if painted else 0), "the canvas image was duplicated"
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
