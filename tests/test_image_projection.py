#!/usr/bin/env python3
"""Check the canvas image a host shows, assembled from tile results, without Blender.

Tiles go through the real profile codec and `CanvasMirror`, then into `ImageProjection`. The cases:
pixels, colour and alpha land where a Blender image keeps them, bottom row first; a tile hanging
over the edge is cut; only changed tiles are written; an older revision never replaces a newer one;
and another image size starts a new image with every tile the mirror holds.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import sys
import types
import unittest


def _pixels(values: list[tuple[float, float, float, float]]) -> bytes:
    return b"".join(struct.pack("<4f", *pixel) for pixel in values)


class ProjectionTests(unittest.TestCase):
    client: types.SimpleNamespace

    def setUp(self) -> None:
        self.profile = self.client.profile
        self.mirror = self.profile.CanvasMirror()
        self.projection = self.client.projection.ImageProjection()
        self.changed: set[tuple[int, int]] = set()

    def _receive(self, width: int, height: int, tiles: list[tuple[int, int, int, bytes]], canvas: int = 1) -> None:
        """Send `tiles` of an image `width` by `height` in tiles of two, as the Realtime Plane does."""
        region = self.profile.EncodeTileResults(
            self.profile.ImageTiles(
                3,
                (width, height),
                2,
                tuple(self.profile.TileResult(x, y, revision) for x, y, revision, _ in tiles),
                b"".join(pixels for *_, pixels in tiles),
            )
        )
        self.mirror.Apply(self.profile.DecodeTileResults(region), canvas)
        self.changed.update((x, y) for x, y, *_ in tiles)

    def _update(self) -> object:
        update = self.projection.Update(self.mirror, self.changed)
        self.changed.clear()
        return update

    def _pixel(self, x: int, y: int) -> tuple[float, ...]:
        """The pixel at (x, y) counted from the top, as the canvas counts."""
        width, height = self.projection.Image.Width, self.projection.Image.Height
        floats = self.projection.Floats()
        start = ((height - 1 - y) * width + x) * 4
        return tuple(floats[start : start + 4])

    def test_pixels_colour_and_alpha_land_bottom_row_first(self) -> None:
        red = (0.5, 0.0, 0.0, 0.5)  # premultiplied: half-transparent full red
        clear = (0.0, 0.0, 0.0, 0.0)
        self._receive(4, 2, [(0, 0, 1, _pixels([red, clear, clear, (0.25, 0.25, 0.25, 1.0)]))])
        update = self._update()
        self.assertTrue(update.Recreated)
        self.assertEqual(update.Written, ((0, 0),))
        self.assertEqual(len(self.projection.Pixels), 4 * 2 * 16)
        self.assertEqual(self._pixel(0, 0), red)
        self.assertEqual(self._pixel(1, 1), (0.25, 0.25, 0.25, 1.0))
        # The top-left canvas pixel is the first pixel of the last row in Blender's layout.
        self.assertEqual(tuple(self.projection.Floats()[4 * 4 : 4 * 4 + 4]), red)
        self.assertEqual(self._pixel(2, 0), clear)  # a tile never sent stays empty

    def test_a_tile_hanging_over_the_edge_is_cut(self) -> None:
        blue = (0.0, 0.0, 1.0, 1.0)
        self._receive(3, 3, [(1, 1, 1, _pixels([blue] * 4))])  # covers (2..3, 2..3); only (2, 2) is inside
        self._update()
        self.assertEqual(len(self.projection.Pixels), 3 * 3 * 16)
        self.assertEqual(self._pixel(2, 2), blue)
        self.assertEqual(self._pixel(1, 2), (0.0, 0.0, 0.0, 0.0))

    def test_only_changed_tiles_are_written(self) -> None:
        grey = _pixels([(0.5, 0.5, 0.5, 1.0)] * 4)
        self._receive(4, 4, [(0, 0, 1, grey), (1, 1, 1, grey)])
        self._update()
        self._receive(4, 4, [(1, 1, 2, _pixels([(1.0, 1.0, 1.0, 1.0)] * 4))], canvas=2)
        update = self._update()
        self.assertFalse(update.Recreated)
        self.assertEqual(update.Written, ((1, 1),))
        self.assertEqual(self.projection.Revision, 2)
        self.assertEqual(self._pixel(0, 0), (0.5, 0.5, 0.5, 1.0))
        self.assertEqual(self._pixel(3, 3), (1.0, 1.0, 1.0, 1.0))

    def test_an_older_revision_never_replaces_a_newer_one(self) -> None:
        self._receive(2, 2, [(0, 0, 5, _pixels([(1.0, 1.0, 1.0, 1.0)] * 4))], canvas=5)
        self._update()
        self._receive(2, 2, [(0, 0, 4, _pixels([(0.0, 0.0, 0.0, 0.0)] * 4))], canvas=4)
        self.changed.add((0, 0))  # even when asked again, what is shown is not older
        update = self._update()
        self.assertEqual(update.Written, ())
        self.assertEqual(update.Stale, 1)
        self.assertEqual(self._pixel(0, 0), (1.0, 1.0, 1.0, 1.0))

    def test_another_size_starts_a_new_image_with_every_tile(self) -> None:
        white = _pixels([(1.0, 1.0, 1.0, 1.0)] * 4)
        self._receive(2, 2, [(0, 0, 1, white)])
        self._update()
        self._receive(4, 2, [(1, 0, 2, white), (0, 0, 2, white)], canvas=2)
        self.changed = {(1, 0)}  # a new image shows every tile, not only the changed one
        update = self._update()
        self.assertTrue(update.Recreated)
        self.assertEqual(update.Written, ((0, 0), (1, 0)))
        self.assertEqual(len(self.projection.Pixels), 4 * 2 * 16)
        self.assertEqual(self._pixel(3, 1), (1.0, 1.0, 1.0, 1.0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--protocol-dir", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    os.environ["FLEXIBLE_DRAWING_PROTOCOL_DIR"] = str(args.protocol_dir)
    root = types.ModuleType("flexible_drawing")
    root.__path__ = [str(args.extension_dir.resolve())]
    sys.modules["flexible_drawing"] = root
    import flexible_drawing.realtime_plane.image_projection as projection
    from flexible_drawing.realtime_plane.profile import Profile

    ProjectionTests.client = types.SimpleNamespace(profile=Profile, projection=projection)
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
