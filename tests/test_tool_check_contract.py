#!/usr/bin/env python3
"""Check the tool screen test's verdicts and native event sequences without touching the desktop."""

from array import array
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from drawing_input import DrawingInput, SyntheticPointer
from test_tools_in_blender import _clearExchange, _hoverPixels, _markerAlpha, _smudgedColour, _waitFor, main


class _Pointer(SyntheticPointer):
    """A recording pointer: window checks succeed, and no native library is loaded."""

    def __init__(self) -> None:
        self.Rate = 10.0
        self.Events = []

    def _bringToFront(self, _pid: int) -> tuple:
        return (100.0, 100.0, 400.0, 328.0)

    def _inFront(self, _pid: int, _x: float, _y: float) -> bool:
        return True

    def _post(self, kind: int, x: float, y: float) -> None:
        self.Events.append((kind, x, y))


class ToolCheckContract(unittest.TestCase):
    """Reject broken rendering evidence and preserve hover's absence of contact events."""

    def testHoverNeverPressesOrDrags(self) -> None:
        pointer = _Pointer()
        with patch("drawing_input.time.sleep"), patch("drawing_input.time.perf_counter", return_value=1.0):
            point = pointer.Hover(1, (0.5, 0.5), 0.2)
        self.assertEqual(point, (300.0, 278.0))
        self.assertEqual(pointer.Events, [(5, *point), (5, *point)])

    def testCrossingIsOneContinuousContact(self) -> None:
        pointer = _Pointer()
        with patch("drawing_input.time.sleep"), patch("drawing_input.time.perf_counter", return_value=1.0):
            pointer.DrawPath(1, ((0.2, 0.2), (0.8, 0.8), (0.2, 0.8), (0.8, 0.2)), 1.0)
        self.assertEqual([item[0] for item in pointer.Events], [1, *([6] * 9), 2])
        self.assertEqual(pointer.Events[0][1:], (180.0, 188.0))
        self.assertEqual(pointer.Events[-1][1:], (420.0, 188.0))

    def testInvalidPathPostsNothing(self) -> None:
        pointer = _Pointer()
        with self.assertRaises(ValueError):
            pointer.DrawPath(1, ((0.5, 0.5), (float("nan"), 0.5)), 1.0)
        self.assertEqual(pointer.Events, [])

    def testPermissionPreflightDoesNotPrompt(self) -> None:
        pointer = _Pointer()
        request = unittest.mock.Mock(return_value=True)
        pointer._cg = SimpleNamespace(CGPreflightPostEventAccess=lambda: False, CGRequestPostEventAccess=request)
        with patch.object(pointer, "_screenLocked", return_value=False):
            self.assertFalse(pointer.Allowed(requestAccess=False))
        request.assert_not_called()
        with patch("drawing_input.sys.platform", "linux"):
            self.assertIsNone(DrawingInput.Open("synthetic", requestAccess=False))

    def testMissingPermissionsSkipBeforeLaunchingAnything(self) -> None:
        arguments = ["test_tools_in_blender.py"]
        for name in ("blender", "package-script", "extension-dir", "library", "wheel-dir", "build-dir"):
            arguments += [f"--{name}", "/unused"]
        for pointer, capture in ((None, True), (_Pointer(), False)):
            with (
                patch("test_tools_in_blender.sys.argv", arguments),
                patch("test_tools_in_blender.DrawingInput.Open", return_value=pointer) as opened,
                patch("test_tools_in_blender._screenCaptureAllowed", return_value=capture),
                patch("test_tools_in_blender.Install") as install,
                patch("test_tools_in_blender.subprocess.Popen") as launch,
            ):
                self.assertEqual(main(), 77)
                opened.assert_called_once_with("synthetic", requestAccess=False)
                install.assert_not_called()
                launch.assert_not_called()

    def testInterruptedPathReleasesTheButton(self) -> None:
        pointer = _Pointer()
        recorded = pointer._post

        def failOnDrag(kind: int, x: float, y: float) -> None:
            if kind == pointer._DRAGGED:
                raise RuntimeError("posting failed")
            recorded(kind, x, y)

        with (
            patch.object(pointer, "_post", side_effect=failOnDrag),
            self.assertRaisesRegex(RuntimeError, "posting failed"),
        ):
            pointer.DrawPath(1, ((0.2, 0.2), (0.8, 0.8)), 1.0)
        self.assertEqual([item[0] for item in pointer.Events], [1, 2])

    def testReusedArtifactsCannotStandInForTheNewRun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exchange = Path(directory)
            for name in (
                "marker.ready",
                "hover.done",
                "pen.png",
                "result.json",
                "hover-position.json",
                "blender.log",
                "review-notes.txt",
            ):
                (exchange / name).write_text("old run", encoding="utf-8")
            _clearExchange(exchange)
            self.assertEqual([item.name for item in exchange.iterdir()], ["review-notes.txt"])

    def testTimeoutAndEarlyExitShowBlenderOutput(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "blender.log"
            log.write_text("host failure evidence", encoding="utf-8")
            for status, error in ((1, RuntimeError), (None, TimeoutError)):
                blender = SimpleNamespace(poll=lambda status=status: status)
                with (
                    patch("test_tools_in_blender.TIMEOUT_S", 0),
                    self.assertRaisesRegex(error, "host failure evidence"),
                ):
                    _waitFor(root / "marker.ready", blender, log)

    def testMarkerCrossingMatchesBothArms(self) -> None:
        size = 128
        pixels = array("f", [0.0]) * (size * size * 4)
        for y in range(24, 105):
            for x in range(24, 105):
                if abs(x - y) <= 2 or abs(x + y - 128) <= 2 or y >= 102:
                    pixels[(y * size + x) * 4 + 3] = 0.5
        result = _markerAlpha(pixels, size, size)
        self.assertEqual(result["crossing_alpha"], 0.5)
        for y in range(62, 67):
            for x in range(62, 67):
                pixels[(y * size + x) * 4 + 3] = 0.75
        with self.assertRaisesRegex(AssertionError, "opacity"):
            _markerAlpha(pixels, size, size)

    def testHoverMustBeVisibleAndThenRemoved(self) -> None:
        size = 64
        before = array("f", [0.2]) * (size * size * 4)
        hover = array("f", before)
        for x, y in ((32, 32), (31, 32), (33, 32), (32, 31), (32, 33)):
            hover[(y * size + x) * 4] = 0.8
        result = _hoverPixels(before, hover, before, size, size, (0.5, 0.5), 12)
        self.assertEqual(result["hover_pixels"], 5)
        with self.assertRaisesRegex(AssertionError, "survived"):
            _hoverPixels(before, hover, hover, size, size, (0.5, 0.5), 12)
        with self.assertRaisesRegex(AssertionError, "no tool hover"):
            _hoverPixels(before, before, before, size, size, (0.5, 0.5), 12)

    def testSmudgeMustCarryColourWithoutAddingPaint(self) -> None:
        size = 32
        before = array("f", [0.0]) * (size * size * 4)
        for y in range(size):
            for x in range(10, 14):
                before[(y * size + x) * 4 : (y * size + x) * 4 + 4] = array("f", [0.5, 0.2, 0.1, 1.0])
        carried = array("f", before)
        for y in range(size):
            # Half the arm's colour moves one pixel to the right, so coverage stays the same.
            carried[(y * size + 13) * 4 + 3] = 0.5
            carried[(y * size + 14) * 4 : (y * size + 14) * 4 + 4] = array("f", [0.25, 0.1, 0.05, 0.5])
        result = _smudgedColour(before, carried)
        self.assertEqual(result["smudge_coloured_empty_pixels"], size)
        with self.assertRaisesRegex(AssertionError, "changed nothing"):
            _smudgedColour(before, before)
        painted = array("f", carried)
        for y in range(size):
            for x in range(15, 20):
                painted[(y * size + x) * 4 + 3] = 1.0
        with self.assertRaisesRegex(AssertionError, "added paint"):
            _smudgedColour(before, painted)


if __name__ == "__main__":
    unittest.main()
