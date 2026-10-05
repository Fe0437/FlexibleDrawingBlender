"""The Realtime Plane in Blender: the buttons that open and stop it, and the timer that follows it.

The Realtime Plane is the primary canvas. It is a separate program with its own window, and it reads
the pen itself, so nothing here touches pointer input: Blender sends only the actions its UI names,
and shows what the Realtime Plane reports back.

The link lives for as long as the add-on is enabled and the timer keeps it moving: it watches the
process, opens a new session when one ends, and moves records. When anything a person can see
changed, the projected UI takes the effective values and the Properties editor redraws, and the
tiles that arrived are shown in the canvas image (see `canvas_image`).

Disabling the add-on or quitting Blender leaves the Realtime Plane running; the next Blender finds it
again. Only "Stop Canvas" ends it.
"""

import logging
from pathlib import Path

import bpy

from ..realtime_plane.link import LinkState
from ..realtime_plane.process import ConfiguredProgram, Program
from . import RealtimePlane, canvas_image
from .ui_projection import Refresh

_logger = logging.getLogger("flexible_drawing")
# The add-on's own package, which is what Blender names its preferences after.
_ADDON = __package__.rpartition(".")[0]
#: How often the timer runs while a session is open: once a frame of a 60 Hz display.
CONNECTED_INTERVAL = 1.0 / 60.0
#: How often it runs otherwise, when there is only a process to watch or a session to open.
WAITING_INTERVAL = 0.25

_watching = False


class RealtimePlanePreferences(bpy.types.AddonPreferences):
    """The add-on's preferences: which Realtime Plane to run."""

    bl_idname = _ADDON

    RealtimePlaneExecutable: bpy.props.StringProperty(
        name="Realtime Plane executable",
        description="Run this Realtime Plane instead of the one the add-on carries; for development",
        subtype="FILE_PATH",
        default="",
    )

    def draw(self, _context: object) -> None:
        self.layout.prop(self, "RealtimePlaneExecutable")


def ResolveProgram() -> Program:
    """The Realtime Plane to start: the development override if one is set, else the bundled one."""
    addon = bpy.context.preferences.addons.get(_ADDON) if hasattr(bpy.context, "preferences") else None
    override = addon.preferences.RealtimePlaneExecutable if addon is not None else ""
    bundled = Path(__file__).resolve().parents[1] / "realtime_plane" / "bin"
    return ConfiguredProgram(bundled, bpy.path.abspath(override) if override else "")


def Status(link: object) -> str:
    """One line saying where the Realtime Plane is, for a person."""
    if link.State is LinkState.CONNECTED:
        # The copy Blender keeps moves with every stroke, so this line does too.
        mirror = link.Session.Mirror
        return f"Realtime Plane: connected; canvas revision {mirror.CanvasRevision}, {len(mirror.Tiles)} tiles copied"
    if link.State is LinkState.CONNECTING:
        return f"Realtime Plane: {link.Message or 'connecting'}"
    return f"Realtime Plane: not running{f' ({link.Message})' if link.Message else ''}"


def _redrawProperties() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()


def _tick() -> float | None:
    """One timer turn: move the link, and show what changed."""
    link = RealtimePlane()
    if link is None or not _watching:
        return None
    changed = link.Advance()
    if canvas_image.Project(link) or changed:
        Refresh(bpy.context.window_manager)
        _redrawProperties()
    return CONNECTED_INTERVAL if link.State is LinkState.CONNECTED else WAITING_INTERVAL


def Watch() -> None:
    """Start following the lent link. Safe to repeat."""
    global _watching
    if not _watching:
        _watching = True
        bpy.app.timers.register(_tick, first_interval=0.0, persistent=True)
        if canvas_image.FileLoaded not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(canvas_image.FileLoaded)


def StopWatching() -> None:
    """Stop following the link; the timer ends on its next turn."""
    global _watching
    _watching = False
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if canvas_image.FileLoaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(canvas_image.FileLoaded)
    canvas_image.Reset()


class OpenCanvasOperator(bpy.types.Operator):
    """Open the Realtime Plane: the external canvas window, which reads the pen itself"""

    bl_idname = "flexible_drawing.canvas_open"
    bl_label = "Open Canvas"

    @classmethod
    def poll(cls, _context: object) -> bool:
        link = RealtimePlane()
        return link is not None and link.State is LinkState.STOPPED

    def execute(self, _context: object) -> set[str]:
        try:
            RealtimePlane().Open()
        except OSError as error:
            self.report({"ERROR"}, f"Could not start the Realtime Plane: {error}")
            return {"CANCELLED"}
        Watch()
        return {"FINISHED"}


class StopCanvasOperator(bpy.types.Operator):
    """Close the Realtime Plane window and end its process"""

    bl_idname = "flexible_drawing.canvas_stop"
    bl_label = "Stop Canvas"

    @classmethod
    def poll(cls, _context: object) -> bool:
        link = RealtimePlane()
        return link is not None and link.State is not LinkState.STOPPED

    def execute(self, _context: object) -> set[str]:
        RealtimePlane().Stop()
        _redrawProperties()
        return {"FINISHED"}
