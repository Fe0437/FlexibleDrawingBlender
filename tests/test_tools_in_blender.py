#!/usr/bin/env python3
"""Check marker compositing, transient hover, tool exchange and Smudge in the packaged Blender canvas.

The runner posts a self-crossing contact into the real Realtime Plane. Its companion inside
Blender checks the committed image's alpha and hash. Window screenshots show a hover point, then
its removal when Blender selects the pen, without another pointer event. Screenshots exclude the
system cursor, so a cursor alone cannot pass the hover assertion. Last, Blender selects Smudge and
the runner drags across both arms of the marker; Blender's image must show the marker's colour
carried into pixels that were empty, without new paint appearing from nowhere.

This takes the screen and pointer. Run only with the person at the unlocked machine's consent.
Missing Accessibility or Screen Recording permission skips (77), without opening permission dialogs.
`--keep DIR` keeps the isolated profile, screenshots and image for review.
"""

from __future__ import annotations

import argparse
from array import array
from collections.abc import Callable
import ctypes
import ctypes.util
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

# Blender's --python loader does not put the script's sibling modules on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drawing_input import DrawingInput, SyntheticPointer
from packaged_blender import INSTALLED, MODULE, Install, RealtimePlaneLog, RealtimePlanePid, StopLeftovers

SKIP = 77
TIMEOUT_S = 90.0
OWNER = "presentation.tool_ui"
PATH = ((0.25, 0.30), (0.75, 0.70), (0.25, 0.70), (0.75, 0.30))
HOVER = (0.70, 0.18)
# Across both diagonals of PATH, below their crossing, so each arm's colour is carried to its right.
# A dark pen line the smudge then crosses, so the drag shows on a light background.
INK = ((0.50, 0.25), (0.50, 0.55))
SMUDGE = ((0.15, 0.40), (0.85, 0.40))


def _markerAlpha(pixels: array, width: int, height: int) -> dict:
    """Compare the bow-tie's crossing with the interiors of its two diagonal arms.

    Locate the shape from nontransparent pixels rather than assuming a window-to-image scale.
    The single contact consists of two diagonals joined at their bottom by a horizontal line.
    Its crossing is the bounding box's centre; quarter points lie well inside the two arms.
    """
    occupied = [index for index in range(width * height) if pixels[index * 4 + 3] > 0.05]
    assert occupied, "the marker stroke never reached the Blender image"
    left, right = min(index % width for index in occupied), max(index % width for index in occupied)
    bottom, top = min(index // width for index in occupied), max(index // width for index in occupied)
    assert right - left >= 40 and top - bottom >= 40, "the self-crossing stroke is too small to check"

    def sample(x: float, y: float) -> float:
        column = round(left + (right - left) * x)
        row = round(bottom + (top - bottom) * y)
        return max(
            pixels[(v * width + u) * 4 + 3] for v in range(row - 1, row + 2) for u in range(column - 1, column + 2)
        )

    crossing = sample(0.5, 0.5)
    arms = (sample(0.25, 0.25), sample(0.75, 0.25))
    assert all(abs(alpha - 0.5) <= 0.015 for alpha in (*arms, crossing)), (
        f"the marker must apply its 0.5 opacity once: crossing {crossing}, arms {arms}"
    )
    assert all(abs(crossing - alpha) <= 0.005 for alpha in arms), (
        f"the crossing accumulated opacity: crossing {crossing}, arms {arms}"
    )
    maximum = max(pixels[index * 4 + 3] for index in occupied)
    assert maximum <= max(arms) + 0.005, f"part of the single marker stroke accumulated opacity: {maximum}"
    return {"crossing_alpha": crossing, "arm_alpha": list(arms), "maximum_alpha": maximum}


def _hoverPixels(
    before: array, hover: array, pen: array, width: int, height: int, position: tuple[float, float], radius: int
) -> dict:
    """Require visible local hover pixels and their removal, at a known point away from the stroke."""
    assert len(before) == len(hover) == len(pen) == width * height * 4, "screenshot shapes differ"
    column, row = round(position[0] * width), round((1.0 - position[1]) * height)
    assert radius < column < width - radius and radius < row < height - radius, "hover patch is outside the screenshot"
    changed = []
    for y in range(row - radius, row + radius + 1):
        for x in range(column - radius, column + radius + 1):
            index = (y * width + x) * 4
            if max(abs(before[index + channel] - hover[index + channel]) for channel in range(3)) > 0.02:
                changed.append(index)
    assert len(changed) >= 3, "the screenshot shows no tool hover point at the posted position"
    assert len(changed) < radius * radius, "the change is larger than a small hover point"
    removalError = max(abs(before[index + channel] - pen[index + channel]) for index in changed for channel in range(3))
    assert removalError <= 0.02, f"the marker's hover point survived the switch to pen: {removalError}"
    return {"hover_pixels": len(changed), "hover_removal_max_error": removalError}


def _smudgedColour(before: array, after: array) -> dict:
    """Compare Blender's image before and after one Smudge contact.

    Smudge picks colour up and lays it down further along the drag, so pixels that were empty gain
    colour, and the total coverage stays near what the marker laid: it moves paint, it adds none.
    """
    count = len(before) // 4
    gained = changed = 0
    for index in range(count):
        alphaBefore, alphaAfter = before[index * 4 + 3], after[index * 4 + 3]
        assert all(0.0 <= after[index * 4 + channel] <= 1.0 for channel in range(4)), "Smudge wrote an invalid value"
        if alphaBefore <= 0.05 < alphaAfter:
            gained += 1
        if any(abs(after[index * 4 + channel] - before[index * 4 + channel]) > 0.01 for channel in range(4)):
            changed += 1
    coverageBefore = sum(before[index * 4 + 3] for index in range(count))
    coverageAfter = sum(after[index * 4 + 3] for index in range(count))
    ratio = coverageAfter / coverageBefore
    assert changed > 0, "Smudge changed nothing in the Blender image"
    assert gained >= 20, f"Smudge carried colour into only {gained} empty pixels"
    assert ratio < 1.25, f"Smudge added paint: coverage grew {ratio:.3f} times"
    return {"smudge_changed_pixels": changed, "smudge_coloured_empty_pixels": gained, "smudge_coverage_ratio": ratio}


def _screenCaptureAllowed() -> bool:
    """Check Screen Recording without prompting or taking a screenshot."""
    if sys.platform != "darwin":
        return False
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    return bool(cg.CGPreflightScreenCaptureAccess())


def _waitFor(path: Path, blender: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + TIMEOUT_S
    while not path.exists():
        if blender.poll() is not None:
            raise RuntimeError(f"Blender ended before {path.name}:\n{log.read_text(encoding='utf-8')}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Blender never reached {path.name}:\n{log.read_text(encoding='utf-8')}")
        time.sleep(0.05)


def _clearExchange(exchange: Path) -> None:
    """Remove only this check's generated evidence and handshake files when artifacts are reused."""
    for name in ("marker", "baseline", "hover", "pen", "ink", "smudge"):
        for suffix in ("ready", "done", "png"):
            (exchange / f"{name}.{suffix}").unlink(missing_ok=True)
    for name in ("result.json", "hover-position.json", "blender.log"):
        (exchange / name).unlink(missing_ok=True)


def _capture(drawing: SyntheticPointer, window: int, path: Path) -> tuple[float, float, float, float]:
    """Capture the checked Realtime Plane window, without shadow or cursor; keep its point bounds."""
    number, bounds = drawing.WindowInfo(window)
    subprocess.run(
        ["/usr/sbin/screencapture", "-x", "-o", "-l", str(number), str(path)],
        check=True,
        capture_output=True,
        timeout=15,
    )
    assert path.is_file() and path.stat().st_size > 0, "the window screenshot is empty"
    return bounds


def _insideBlender(exchange: Path, module: str) -> None:
    """Run the real host turns, select tools through its UI, and inspect its actual image."""
    import bpy

    presentation = importlib.import_module(f"{module}.presentation")
    canvas = importlib.import_module(f"{module}.presentation.canvas_image")
    projection = importlib.import_module(f"{module}.presentation.ui_projection")
    linkState = importlib.import_module(f"{module}.realtime_plane.link").LinkState

    def link() -> object:
        return presentation.RealtimePlane()

    def turn() -> None:
        current = link()
        current.Advance()
        canvas.Project(current)
        projection.Refresh(bpy.context.window_manager)
        time.sleep(1.0 / 60.0)

    def until(what: str, condition: Callable[[], bool]) -> None:
        deadline = time.monotonic() + TIMEOUT_S
        while not condition():
            assert time.monotonic() < deadline, f"timed out waiting for {what}: {link().Message}"
            turn()

    def quiet() -> None:
        revision, since = -1, time.monotonic()
        while time.monotonic() - since < 0.75:
            current = link().Session.Mirror.CanvasRevision
            if current != revision:
                revision, since = current, time.monotonic()
            turn()

    def image() -> object:
        images = [item for item in bpy.data.images if canvas.SURFACE_KEY in item]
        assert len(images) == 1, f"expected one canvas image, found {len(images)}"
        return images[0]

    def pixels(item: object) -> array:
        result = array("f", bytes(4 * len(item.pixels)))
        item.pixels.foreach_get(result)
        return result

    def imageHash() -> str:
        return hashlib.sha256(pixels(image()).tobytes()).hexdigest()

    def select(tool: str) -> None:
        controls = bpy.context.window_manager.flexible_drawing_ui
        selector = next(item for item in controls.bl_rna.properties if item.name == "Active tool")
        setattr(controls, selector.identifier, tool)
        until(f"{tool} to take effect", lambda: link().Effective(OWNER, "active_tool") == tool)

    def waitStep(step: str) -> None:
        (exchange / f"{step}.ready").touch()
        until(step, lambda: (exchange / f"{step}.done").exists())
        quiet()

    assert bpy.ops.flexible_drawing.canvas_open() == {"FINISHED"}
    until("the canvas session", lambda: link().State is linkState.CONNECTED)
    until("the initial tool state", lambda: link().Effective(OWNER, "active_tool") is not None)
    select("freehand.marker")
    waitStep("marker")
    marker = _markerAlpha(pixels(image()), *image().size)
    markerHash = imageHash()
    image().save_render(str(exchange / "marker.png"))
    waitStep("baseline")
    assert imageHash() == markerHash, "taking a screenshot changed the Blender image"
    waitStep("hover")
    assert imageHash() == markerHash, "hover preview reached the Blender image"
    # No pointer event is posted from here through the pen screenshot. Even though the pen itself
    # supports hover, the marker's old point must be cleared, not redrawn as if it belonged to it.
    select("freehand.pen")
    waitStep("pen")
    assert imageHash() == markerHash, "tool exchange changed the Blender image"
    screenshots = [
        bpy.data.images.load(str(exchange / f"{name}.png"), check_existing=False)
        for name in ("baseline", "hover", "pen")
    ]
    try:
        assert all(tuple(item.size) == tuple(screenshots[0].size) for item in screenshots), "the window changed size"
        metadata = json.loads((exchange / "hover-position.json").read_text(encoding="utf-8"))
        hover = _hoverPixels(
            *(pixels(item) for item in screenshots),
            *screenshots[0].size,
            tuple(metadata["position"]),
            max(12, round(screenshots[0].size[0] * metadata["radius_fraction"])),
        )
    finally:
        for item in screenshots:
            bpy.data.images.remove(item)
    exchangedHash = imageHash()
    waitStep("ink")
    image().save_render(str(exchange / "ink.png"))
    # Smudge runs only where a GPU runtime is, as in the Realtime Plane.
    select("freehand.smudge")
    beforeSmudge = pixels(image())
    waitStep("smudge")
    smudge = _smudgedColour(beforeSmudge, pixels(image()))
    image().save_render(str(exchange / "smudge.png"))
    result = {
        **marker,
        **hover,
        **smudge,
        "image_hash_before_hover": markerHash,
        "image_hash_after_hover_and_exchange": exchangedHash,
        "image_size": list(image().size),
    }
    (exchange / "result.json").write_text(json.dumps(result), encoding="utf-8")
    assert bpy.ops.flexible_drawing.canvas_stop() == {"FINISHED"}
    print("FLEXIBLE_DRAWING_TOOLS_IN_BLENDER_OK", flush=True)


def main() -> int:
    """Run with isolated packaged processes; permission checks happen before launch or pointer work."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inside-blender", action="store_true")
    parser.add_argument("--exchange", type=Path)
    parser.add_argument("--module", default=MODULE)
    for name in ("blender", "package-script", "extension-dir", "library", "wheel-dir", "build-dir"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep", type=Path)
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(arguments)
    if args.inside_blender:
        if args.exchange is None:
            parser.error("--inside-blender needs --exchange")
        _insideBlender(args.exchange, args.module)
        return 0
    for name in ("blender", "package_script", "extension_dir", "library", "wheel_dir", "build_dir"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required")
    drawing = DrawingInput.Open("synthetic", requestAccess=False)
    if drawing is None or not _screenCaptureAllowed():
        print("SKIP: grant Accessibility and Screen Recording to the terminal, and unlock the screen")
        return SKIP
    scope = f"tool-check-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="flexible-drawing-tools-") as directory:
        root = Path(directory) if args.keep is None else args.keep.resolve()
        root.mkdir(parents=True, exist_ok=True)
        exchange = root / "exchange"
        exchange.mkdir(exist_ok=True)
        _clearExchange(exchange)
        blender = None
        logPath = exchange / "blender.log"
        blenderLog = logPath.open("w", encoding="utf-8")
        try:
            environment = Install(root, args, scope, buildDir=args.build_dir)
            blender = subprocess.Popen(
                [
                    str(args.blender),
                    "--background",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(Path(__file__).resolve()),
                    "--",
                    "--inside-blender",
                    "--exchange",
                    str(exchange),
                    "--module",
                    MODULE,
                ],
                env=environment,
                stdout=blenderLog,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _waitFor(exchange / "marker.ready", blender, logPath)
            window = RealtimePlanePid(root, scope)
            drawing.DrawPath(window, PATH, 3.0)
            (exchange / "marker.done").touch()
            _waitFor(exchange / "baseline.ready", blender, logPath)
            _capture(drawing, window, exchange / "baseline.png")
            (exchange / "baseline.done").touch()
            _waitFor(exchange / "hover.ready", blender, logPath)
            point = drawing.Hover(window, HOVER)
            time.sleep(0.25)  # let the native present complete before capture; this is no timing verdict
            left, top, width, height = _capture(drawing, window, exchange / "hover.png")
            # PNG dimensions may be Retina-scaled; Blender scales this normalized centre and radius.
            (exchange / "hover-position.json").write_text(
                json.dumps(
                    {
                        "position": [(point[0] - left) / width, (point[1] - top) / height],
                        "radius_fraction": 12.0 / width,
                    }
                ),
                encoding="utf-8",
            )
            (exchange / "hover.done").touch()
            _waitFor(exchange / "pen.ready", blender, logPath)
            time.sleep(0.25)
            _capture(drawing, window, exchange / "pen.png")
            (exchange / "pen.done").touch()
            _waitFor(exchange / "ink.ready", blender, logPath)
            drawing.DrawPath(window, INK, 1.0)
            (exchange / "ink.done").touch()
            _waitFor(exchange / "smudge.ready", blender, logPath)
            drawing.DrawPath(window, SMUDGE, 2.0)
            time.sleep(0.25)  # let the native present complete before capture
            _capture(drawing, window, exchange / "smudge-window.png")
            (exchange / "smudge.done").touch()
            blender.wait(timeout=TIMEOUT_S)
            blenderLog.flush()
            output = logPath.read_text(encoding="utf-8")
            assert blender.returncode == 0 and "FLEXIBLE_DRAWING_TOOLS_IN_BLENDER_OK" in output, output
            result = {
                "when": datetime.now().isoformat(timespec="seconds"),
                "input": drawing.Description,
                **json.loads((exchange / "result.json").read_text(encoding="utf-8")),
            }
        except Exception:
            if blender is not None and blender.poll() is None:
                blender.kill()
                blender.wait(timeout=10)
            blenderLog.flush()
            print(f"Blender's log:\n{logPath.read_text(encoding='utf-8')}", file=sys.stderr)
            if (root / INSTALLED).is_dir():
                print(f"The Realtime Plane's log:\n{RealtimePlaneLog(root, scope)}", file=sys.stderr)
            raise
        finally:
            if blender is not None and blender.poll() is None:
                blender.kill()
                blender.wait(timeout=10)
            blenderLog.close()
            if (root / INSTALLED).is_dir():
                StopLeftovers(root, scope)
    text = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("FLEXIBLE_DRAWING_TOOLS_IN_BLENDER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
