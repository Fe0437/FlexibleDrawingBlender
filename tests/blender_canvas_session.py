"""Inside Blender: what was drawn in the real Realtime Plane must be the image and the material.

Run twice by `test_canvas_in_blender.py`, as
``blender --background [FILE] --python blender_canvas_session.py -- --module M --phase P --exchange DIR``.
Strokes are drawn by the runner, outside Blender; this script and the runner take turns through
files in `--exchange`: the script writes `<step>.ready` when it waits for a stroke, and the runner
writes `<step>.drawing` when it starts drawing and `<step>.drawn` when it is done.

Phase `first` opens the canvas, waits for a stroke, binds the canvas into a plane's material and
checks that the image, every tile of it, and a render of the material show exactly what the session
received. During a long stroke it times how far apart the image updates are. It saves the file,
records the image's hash in `result-first.json`, and lets go of the Realtime Plane without stopping it.

Phase `second` is a new Blender with the saved file. It finds the Realtime Plane still running,
opens a new session, and must rebuild the image to the same hash with no stroke drawn; then once
more after the image is deleted. It stops the canvas and records `result-second.json`.

In the background there is no event loop, so the script runs the add-on's timer turn itself.
"""

from __future__ import annotations

import argparse
from array import array
from collections.abc import Callable
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import sys
import time

import bpy

TIMEOUT_S = 60.0
TURN_S = 1.0 / 60.0
QUIET_S = 0.75
#: Most time between two image updates while a stroke is drawn: a few host turns, never a frame stall.
UPDATE_GAP_LIMIT_S = 0.25


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True)
    parser.add_argument("--phase", choices=("first", "second"), required=True)
    parser.add_argument("--exchange", type=Path, required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


arguments = _arguments()
presentation = importlib.import_module(f"{arguments.module}.presentation")
realtime_plane = importlib.import_module(f"{arguments.module}.presentation.realtime_plane")
canvas_image = importlib.import_module(f"{arguments.module}.presentation.canvas_image")
canvas_binding = importlib.import_module(f"{arguments.module}.host.canvas_binding")
LinkState = importlib.import_module(f"{arguments.module}.realtime_plane.link").LinkState


def _link() -> object:
    return presentation.RealtimePlane()


def _until(what: str, condition: Callable[[], bool], during: Callable[[bool], None] | None = None) -> None:
    """Take host turns until `condition` holds; `during` hears whether each turn changed the image."""
    started = time.monotonic()
    while not condition():
        if time.monotonic() - started > TIMEOUT_S:
            raise TimeoutError(f"timed out waiting for {what}: {_link().Message}")
        _turn(during)


def _turn(during: Callable[[bool], None] | None = None) -> None:
    link = _link()
    link.Advance()
    changed = canvas_image.Project(link)
    if during is not None:
        during(changed)
    time.sleep(TURN_S)


def _connected() -> bool:
    return _link().State is LinkState.CONNECTED


def _image() -> object | None:
    images = [image for image in bpy.data.images if canvas_image.SURFACE_KEY in image]
    assert len(images) <= 1, "the canvas has more than one image"
    return images[0] if images else None


def _quiet() -> None:
    """Take turns until the session has received nothing new for a while."""
    revision, since = -1, time.monotonic()
    while time.monotonic() - since < QUIET_S:
        current = _link().Session.Mirror.CanvasRevision
        if current != revision:
            revision, since = current, time.monotonic()
        _turn()


def _waitForStroke(step: str, during: Callable[[bool], None] | None = None) -> None:
    """Ask the runner for a stroke and take turns until it is drawn and has arrived."""
    (arguments.exchange / f"{step}.ready").touch()
    _until(f"the runner to draw {step}", lambda: (arguments.exchange / f"{step}.drawn").exists(), during)
    _quiet()


def _imagePixels() -> array:
    image = _image()
    pixels = array("f", bytes(4 * len(image.pixels)))
    image.pixels.foreach_get(pixels)
    return pixels


def _imageHash() -> str:
    return hashlib.sha256(_imagePixels().tobytes()).hexdigest()


def _tileHashesMatch() -> int:
    """Check every tile the session holds against the same tile of the image; return how many."""
    mirror = _link().Session.Mirror
    shape = mirror.Image
    pixels = _imagePixels()
    checked = 0
    for (x, y), (_revision, data) in mirror.Tiles.items():
        received = bytearray()
        shown = bytearray()
        for row in range(shape.TileExtent):
            top = y * shape.TileExtent + row
            columns = min(shape.TileExtent, shape.Width - x * shape.TileExtent)
            if top >= shape.Height or columns <= 0:
                continue
            start = row * shape.TileExtent * 16
            received += data[start : start + columns * 16]
            first = ((shape.Height - 1 - top) * shape.Width + x * shape.TileExtent) * 4
            shown += pixels[first : first + columns * 4].tobytes()
        assert hashlib.sha256(received).digest() == hashlib.sha256(shown).digest(), f"tile {(x, y)} differs"
        checked += 1
    return checked


def _bindPlane() -> object:
    """A plane with the canvas's proportions, its material bound to the canvas."""
    if bpy.context.scene.get("flexible_drawing_document_id") is None:
        assert bpy.ops.flexible_drawing.document_create() == {"FINISHED"}
    shape = _link().Session.Mirror.Image
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    plane = bpy.context.object
    plane.scale = (shape.Width / shape.Height, 1.0, 1.0)
    assert bpy.ops.flexible_drawing.canvas_material() == {"FINISHED"}
    return plane


def _renderMatchesTheImage(plane: object, directory: Path) -> float:
    """Render the bound material straight on and compare it with the image; return the mean error.

    The render is a scene of its own holding only the plane and a camera, so nothing of the scene a
    person works in, such as Blender's default cube and light, gets in front of it. It shows the
    canvas by emission only, on a black, transparent world, one sample per pixel at the image's own
    resolution, so each rendered pixel is one texel of the image and the premultiplied colour comes
    out as it went in.
    """
    scene = bpy.data.scenes.new("Canvas render")
    scene.collection.objects.link(plane)
    shape = _link().Session.Mirror.Image
    original = plane.active_material
    material = original.copy()
    plane.active_material = material
    tree = material.node_tree
    shader = tree.nodes["Principled BSDF"]
    (node,) = canvas_binding.BoundNodes(material, shape.Surface)
    node.interpolation = "Closest"
    shader.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    for link in list(shader.inputs["Base Color"].links):
        tree.links.remove(link)
    tree.links.new(node.outputs["Color"], shader.inputs["Emission Color"])
    shader.inputs["Emission Strength"].default_value = 1.0
    shader.inputs["Specular IOR Level"].default_value = 0.0
    camera = bpy.data.objects.new("Canvas camera", bpy.data.cameras.new("Canvas camera"))
    scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 2.0 * shape.Width / shape.Height
    camera.location = (0.0, 0.0, 5.0)
    camera.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = camera
    scene.world = bpy.data.worlds.new("Canvas world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.filter_width = 0.01
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = shape.Width, shape.Height
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    path = directory / "material.exr"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True, scene=scene.name)
    image = _imagePixels()
    # The image beside the render, for whoever reads a failure. Saving the canvas image itself would
    # turn it into a file image and drop its pixels, so its pixels are written into another.
    copy = bpy.data.images.new("Canvas copy", shape.Width, shape.Height, alpha=True, float_buffer=True)
    copy.pixels.foreach_set(image)
    copy.filepath_raw = str(directory / "canvas.exr")
    copy.file_format = "OPEN_EXR"
    copy.save()
    bpy.data.images.remove(copy)
    rendered = bpy.data.images.load(str(path))
    rendered.colorspace_settings.name = canvas_image.COLOR_SPACE
    render = array("f", bytes(4 * len(rendered.pixels)))
    rendered.pixels.foreach_get(render)
    assert len(render) == len(image), (len(render), len(image))
    error = sum(abs(a - b) for a, b in zip(render, image, strict=True)) / len(image)
    # Leave the file as a person would have it: their material, and nothing of the render.
    bpy.data.images.remove(rendered)
    plane.active_material = original
    bpy.data.materials.remove(material)
    bpy.data.objects.remove(camera)
    bpy.data.worlds.remove(scene.world)
    bpy.data.scenes.remove(scene)
    return error


def _first() -> dict:
    assert bpy.ops.flexible_drawing.canvas_open() == {"FINISHED"}
    _until("a session with the real Realtime Plane", _connected)
    _waitForStroke("stroke")
    mirror = _link().Session.Mirror if _link().Session is not None else None
    assert _image() is not None, (
        f"the stroke did not reach Blender: link {_link().State}, {_link().Message!r}; "
        f"mirror image {mirror.Image if mirror else None}, {len(mirror.Tiles) if mirror else 0} tiles, "
        f"canvas revision {mirror.CanvasRevision if mirror else 0}; {canvas_image.Status(_link())}"
    )
    tiles = _tileHashesMatch()
    plane = _bindPlane()
    renderError = _renderMatchesTheImage(plane, arguments.exchange)
    assert renderError < 0.01, f"the material render differs from the canvas image by {renderError}"

    # While a long stroke is drawn, the image follows it in steps no farther apart than the limit.
    updates: list[float] = []

    def timed(changed: bool) -> None:
        if changed and (arguments.exchange / "long.drawing").exists():
            updates.append(time.monotonic())

    _waitForStroke("long", timed)
    gaps = [later - earlier for earlier, later in itertools.pairwise(updates)]
    assert len(updates) > 5, f"the image changed only {len(updates)} times during a long stroke"
    assert max(gaps) <= UPDATE_GAP_LIMIT_S, f"the image stalled for {max(gaps):.3f} s during a long stroke"
    longTiles = _tileHashesMatch()

    path = arguments.exchange / "canvas.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(path)) == {"FINISHED"}
    return {
        "image_hash": _imageHash(),
        "tiles_checked": tiles + longTiles,
        "render_mean_error": renderError,
        "updates_during_long_stroke": len(updates),
        "largest_update_gap_s": max(gaps),
        "image_size": list(_image().size),
    }


def _second(first: dict) -> dict:
    # Enabling the add-on found the Realtime Plane still running; a new session sends the whole canvas.
    assert _link().Process is not None, "the Realtime Plane did not survive the first Blender"
    _until("a session with the surviving Realtime Plane", _connected)

    def rebuilt() -> bool:
        return _image() is not None and _imageHash() == first["image_hash"]

    _until("the image rebuilt with no stroke drawn", rebuilt)
    surface = _link().Session.Mirror.Image.Surface
    material = next(m for m in bpy.data.materials if canvas_binding.BoundNodes(m, surface))
    assert canvas_binding.BoundNodes(material, surface)[0].image == _image(), "the reopened material lost the image"

    bpy.data.images.remove(_image())
    _until("the deleted image rebuilt", rebuilt)
    assert canvas_binding.BoundNodes(material, surface)[0].image == _image(), "the material lost the rebuilt image"
    assert bpy.ops.flexible_drawing.canvas_stop() == {"FINISHED"}
    return {"rebuilt_hash": first["image_hash"], "material": material.name}


def main() -> None:
    if arguments.phase == "first":
        result = _first()
    else:
        result = _second(json.loads((arguments.exchange / "result-first.json").read_text(encoding="utf-8")))
    (arguments.exchange / f"result-{arguments.phase}.json").write_text(json.dumps(result), encoding="utf-8")
    print(f"FLEXIBLE_DRAWING_CANVAS_{arguments.phase.upper()}_OK", flush=True)


main()
