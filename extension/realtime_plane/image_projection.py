"""The canvas image a host shows, assembled from the tiles the Realtime Plane sent.

This is the part of showing the canvas that needs no Blender: it keeps one image's pixels in the
layout a Blender image stores them, and writes into it only the tiles that changed. A host copies
`Pixels` into its own image afterwards. The pixels here are a copy of a copy: the Realtime Plane's
canvas stays the only owner of what was painted, and this is rebuilt from it whenever it is lost.

Tiles arrive top row first, as the canvas has them. A Blender image keeps its bottom row first, so
rows are turned over on the way in. A tile at the right or bottom edge may hang over the image; the
part past the edge is left out.

```python
projection = ImageProjection()
update = projection.Update(session.Mirror, session.ChangedTiles)
session.ChangedTiles.clear()
image.pixels.foreach_set(projection.Floats())
```
"""

from __future__ import annotations

from typing import NamedTuple

#: Bytes of one pixel: red, green, blue and alpha as 32-bit floats.
PIXEL_BYTES = 16


class ProjectionUpdate(NamedTuple):
    """What one update changed."""

    Recreated: bool
    """The image is new or has another size, so every tile was written again."""
    Written: tuple[tuple[int, int], ...]
    """The tiles whose pixels were written, by (x, y) tile coordinate."""
    Stale: int
    """Changed tiles skipped because what is shown is already as new or newer."""


class ImageProjection:
    """One canvas image in a host's layout, kept current tile by tile."""

    def __init__(self) -> None:
        self.Image = None
        """The image shown, as the mirror describes it; None before the first tile."""
        self.Pixels = bytearray()
        """Width times height pixels of four 32-bit floats, premultiplied linear RGBA, bottom row first."""
        self.Revision = 0
        """The canvas revision the pixels show."""
        self._shown: dict[tuple[int, int], int] = {}

    def Floats(self) -> memoryview:
        """The pixels as floats, for a host image to copy."""
        return memoryview(self.Pixels).cast("f")

    def Update(self, mirror: object, changed: set[tuple[int, int]]) -> ProjectionUpdate:
        """Write the tiles in `changed` that the mirror holds newer than what is shown."""
        recreated = mirror.Image != self.Image
        if recreated:
            self.Image = mirror.Image
            self._shown.clear()
            size = 0 if self.Image is None else self.Image.Width * self.Image.Height * PIXEL_BYTES
            self.Pixels = bytearray(size)
            changed = set(mirror.Tiles)  # a new image shows every tile the mirror has
        written = []
        stale = 0
        for tile in sorted(changed):
            kept = mirror.Tiles.get(tile)
            if kept is None:
                continue
            revision, pixels = kept
            if revision <= self._shown.get(tile, 0):
                stale += 1
                continue
            self._write(tile, pixels)
            self._shown[tile] = revision
            written.append(tile)
        self.Revision = mirror.CanvasRevision
        return ProjectionUpdate(recreated, tuple(written), stale)

    def _write(self, tile: tuple[int, int], pixels: bytes) -> None:
        image = self.Image
        extent = image.TileExtent
        left = tile[0] * extent
        columns = min(extent, image.Width - left)
        if left < 0 or columns <= 0:
            return
        rowBytes = columns * PIXEL_BYTES
        for row in range(extent):
            y = tile[1] * extent + row  # from the top, as the canvas counts
            if not 0 <= y < image.Height:
                continue
            target = ((image.Height - 1 - y) * image.Width + left) * PIXEL_BYTES
            source = row * extent * PIXEL_BYTES
            self.Pixels[target : target + rowBytes] = pixels[source : source + rowBytes]
