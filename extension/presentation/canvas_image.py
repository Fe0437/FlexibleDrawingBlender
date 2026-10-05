"""The Realtime Plane canvas as a Blender image, kept current from the Blender timer.

The image is a projection, never the canvas itself. Its pixels come from the copy the session
keeps, and the Realtime Plane's canvas stays their only owner: the image is rebuilt from the
whole canvas whenever a session opens, and nothing Blender does to it travels back.

There is one image per canvas surface, found again by the surface identity it carries, so enabling
the add-on again, or opening another session, reuses it instead of adding another. When the image
is deleted, it is made again from the pixels already received, and every material node bound to the
surface gets it back (see `host.canvas_binding`). A reopened file keeps the image but not its
pixels, so opening a file starts the projection again and the session's copy fills it. Its pixels are
32-bit floats in linear light with the colour premultiplied by alpha, as the Realtime Plane sends
them, and the image says so, so Blender's colour management reads them correctly.

Everything here runs on Blender's main thread, inside the timer that moves the link.
"""

from __future__ import annotations

import logging

import bpy

from ..host import canvas_binding
from ..realtime_plane.image_projection import ImageProjection
from ..realtime_plane.link import LinkState

_logger = logging.getLogger("flexible_drawing")

#: The name a new canvas image gets; a person may rename it, since it is found by `SURFACE_KEY`.
IMAGE_NAME = "Flexible Drawing Canvas"
#: The image's custom property naming the canvas surface it shows; bound nodes carry the same one.
SURFACE_KEY = canvas_binding.SURFACE
#: How Blender is told the pixels are linear.
COLOR_SPACE = "Linear Rec.709"


# The session being followed, its projection, and what went wrong last.
_session = 0
_projection = ImageProjection()
_error = ""


def Reset() -> None:
    """Forget the projection; the next session rebuilds the image from the whole canvas."""
    global _session, _projection, _error
    _session = 0
    _projection = ImageProjection()
    _error = ""


@bpy.app.handlers.persistent
def FileLoaded(*_arguments: object) -> None:
    """Blender opened a file: its canvas image has no pixels, so fill it again from the session."""
    Reset()


def FindImage(surface: int) -> object | None:
    """The image that shows `surface`, if there is one."""
    key = canvas_binding.SurfaceKey(surface)
    for image in bpy.data.images:
        if image.get(SURFACE_KEY) == key:
            return image
    return None


def _imageFor(surface: int, width: int, height: int) -> object:
    """The surface's image at this size: the existing one, resized if needed, or a new one."""
    image = FindImage(surface)
    if image is not None and not image.is_float:
        bpy.data.images.remove(image)  # pixels of another precision cannot hold these
        image = None
    if image is None:
        image = bpy.data.images.new(IMAGE_NAME, width, height, alpha=True, float_buffer=True)
        image[SURFACE_KEY] = canvas_binding.SurfaceKey(surface)
        restored = canvas_binding.Restore(bpy.data.materials, image, surface)
        if restored:
            _logger.info("[realtime_plane] canvas image made again for %d material node(s)", restored)
    elif tuple(image.size) != (width, height):
        image.scale(width, height)
    image.alpha_mode = "PREMUL"
    if image.colorspace_settings.name != COLOR_SPACE:
        image.colorspace_settings.name = COLOR_SPACE
    return image


def Project(link: object) -> bool:
    """Show what the session received since the last turn. Returns whether the image changed."""
    global _session, _error
    if link.State is not LinkState.CONNECTED:
        return False
    session = link.Session
    if session.Id != _session:
        Reset()  # a new session sends the whole canvas, which may be another process's
        _session = session.Id
    projection = _projection
    mirror = session.Mirror
    if mirror.Image is None:
        return False
    # A deleted image is shown again from what was received, even if nothing new arrived.
    missing = projection.Image is not None and FindImage(projection.Image.Surface) is None
    if session.ChangedTiles or mirror.Image != projection.Image:
        update = projection.Update(mirror, session.ChangedTiles)
        session.ChangedTiles.clear()
        if not update.Written and not update.Recreated and not missing:
            return False
    elif not missing:
        return False
    try:
        shape = projection.Image
        image = _imageFor(shape.Surface, shape.Width, shape.Height)
        image.pixels.foreach_set(projection.Floats())
        image.update()
        _redrawViews()
        _error = ""
    except (RuntimeError, ReferenceError, TypeError, ValueError) as error:
        # The canvas goes on; the next change tries again, and the person sees why it is behind.
        _error = str(error)
        _logger.warning("[realtime_plane] could not update the canvas image: %s", error)
        return False
    return True


def _redrawViews() -> None:
    """Redraw the editors that may show the image: Image Editors, and 3D views showing materials."""
    for window in getattr(bpy.context.window_manager, "windows", ()):
        for area in window.screen.areas:
            if area.type in ("IMAGE_EDITOR", "VIEW_3D"):
                area.tag_redraw()


def CanvasImage() -> object | None:
    """The canvas image, once the canvas has been shown at least once."""
    return next((image for image in bpy.data.images if SURFACE_KEY in image), None)


class ShowCanvasOperator(bpy.types.Operator):
    """Show the canvas image in an Image Editor window, updated while you draw in the Realtime Plane"""

    bl_idname = "flexible_drawing.canvas_show"
    bl_label = "Show Canvas"

    @classmethod
    def poll(cls, context: object) -> bool:
        return CanvasImage() is not None and getattr(context, "area", None) is not None

    def execute(self, _context: object) -> set[str]:
        image = CanvasImage()
        # An Image Editor that already shows it is enough; otherwise a window of its own.
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "IMAGE_EDITOR" and area.spaces.active.image == image:
                    return {"FINISHED"}
        # Blender makes a window only through an operator, and the new window holds one area, copied
        # from the active one; that area becomes the Image Editor.
        if bpy.ops.wm.window_new() != {"FINISHED"}:
            self.report({"ERROR"}, "Blender did not open a window")
            return {"CANCELLED"}
        area = bpy.context.window_manager.windows[-1].screen.areas[0]
        area.type = "IMAGE_EDITOR"
        area.spaces.active.image = image
        return {"FINISHED"}


def Status(link: object) -> str:
    """How far the image is behind what Blender received, or why it is not being updated."""
    if _error:
        return f"Canvas image not updated: {_error}"
    if link.State is not LinkState.CONNECTED or _projection.Image is None:
        return "Canvas image: waiting for the canvas"
    behind = link.Session.Mirror.CanvasRevision - _projection.Revision
    return f"Canvas image: revision {_projection.Revision}" + (f", {behind} behind" if behind else "")
