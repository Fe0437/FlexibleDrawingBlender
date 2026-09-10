"""Open Blender editor areas as Flexible Drawing viewports, and map pointer positions to the canvas.

Two Blender editors can host the viewport, and they differ in how much work a pointer position
costs. The Image Editor shows the canvas flat: its View2D already maps region pixels onto the
displayed image, with pan and zoom applied, so `ImageEditorRegionToCanvas` finishes the conversion
in two multiplications. The 3D View places the canvas somewhere in the scene, so the same conversion
needs a canvas plane and a view ray. That mapping does not exist yet, which is why there is one
conversion function here and not two: the 3D View can host the sidebar today, but not pointer input.

The two conversions are kept as separate named functions rather than behind one signature because
they do not take the same arguments. A flat canvas is measured against an extent; a canvas in the
scene is measured against a plane. One signature covering both would have to be widened or replaced
as soon as the second arrives.

This module changes only the area the caller supplies and converts coordinates. It does not create
windows, draw canvas tiles, or own document state.
"""

from __future__ import annotations

from dataclasses import dataclass

IMAGE_EDITOR_SPACE_TYPE = "IMAGE_EDITOR"
VIEW_3D_SPACE_TYPE = "VIEW_3D"
#: The Blender editors that can show the Flexible Drawing sidebar and host the canvas.
VIEWPORT_SPACE_TYPES = (IMAGE_EDITOR_SPACE_TYPE, VIEW_3D_SPACE_TYPE)
SIDEBAR_REGION_TYPE = "UI"
SIDEBAR_CATEGORY = "Flexible Drawing"


@dataclass(frozen=True)
class CanvasExtent:
    """The drawing width and height used to convert pointer positions to canvas units.

    Provisional: the engine owns one live canvas and does not report its size, so a host has to be
    told the extent it is drawing against. When the engine reports the extent, it comes from the
    document and this record is built from that. Do not store an extent of your own alongside the
    document, and do not treat a host-chosen extent as the canvas's identity.
    """

    Width: float
    Height: float


def RevealViewportSidebar(area: object | None) -> bool:
    """Reveal the sidebar and select the Flexible Drawing tab, if Blender will accept both yet.

    Blender builds a sidebar's list of tabs the first time it draws that region, and refuses to
    select a tab while the list is still empty. An area whose editor has only just changed has not
    been drawn, so the first attempt normally fails. That is why refusal is reported rather than
    raised: this asks the area to redraw and returns False, and the caller retries.
    """
    if area is None or getattr(area, "type", None) not in VIEWPORT_SPACE_TYPES:
        return False

    spaces = getattr(area, "spaces", None)
    activeSpace = getattr(spaces, "active", None)
    if activeSpace is None or not hasattr(activeSpace, "show_region_ui"):
        return False
    activeSpace.show_region_ui = True

    sidebarFound = False
    for region in getattr(area, "regions", ()):
        if getattr(region, "type", None) != SIDEBAR_REGION_TYPE:
            continue
        if region.is_property_readonly("active_panel_category"):
            area.tag_redraw()
            return False
        region.active_panel_category = SIDEBAR_CATEGORY
        sidebarFound = True
    return sidebarFound


def OpenViewport(area: object | None, spaceType: str) -> bool:
    """Turn one Blender editor area into the viewport.

    Revealing the sidebar is left to the caller, because Blender cannot select a tab until it has
    drawn the new editor, which happens after the calling operator returns. False means Blender
    supplied no editor area or refused the requested editor type.
    """
    if spaceType not in VIEWPORT_SPACE_TYPES:
        raise ValueError(f"unsupported Flexible Drawing viewport editor: {spaceType}")
    if area is None:
        return False
    area.type = spaceType
    return getattr(area, "type", None) == spaceType


def OpenViewportWindow(bpy: object, spaceType: str) -> object | None:
    """Open the viewport in a new Blender window, and return the area that now fills it.

    A canvas wants a window of its own rather than a corner of the one the user is already working
    in. Blender makes windows only through an operator, and the window it makes holds exactly one
    area, copied from the active one, so that area is the one changed to the requested editor.

    `bpy` is passed in rather than imported so this module stays testable without Blender.

    Returns None when Blender refused to make the window, which is what happens when it is called
    with no active area to copy.
    """
    if bpy.ops.wm.window_new() != {"FINISHED"}:
        return None
    area = bpy.context.window_manager.windows[-1].screen.areas[0]
    return area if OpenViewport(area, spaceType) else None


def ImageEditorRegionToCanvas(region: object, x: float, y: float, extent: CanvasExtent) -> tuple[float, float]:
    """Convert a pointer position in an Image Editor region to canvas units.

    Blender reports pointer positions in region pixels with y increasing upward. The Image Editor's
    View2D turns those into the displayed image's normalized space, where (0, 0) is the bottom-left
    corner and (1, 1) the top-right, and pan and zoom are already accounted for. The engine measures
    the canvas from its top-left corner with y increasing downward, so the vertical axis is flipped
    here and nowhere else.

    Positions outside the canvas are returned as they are. A stroke that leaves the canvas is the
    caller's decision to make, and clamping here would quietly bend it back instead.
    """
    u, v = region.view2d.region_to_view(x, y)
    return u * extent.Width, (1.0 - v) * extent.Height
