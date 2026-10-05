#!/usr/bin/env python3
"""Compare the Realtime Plane's pen-to-present latency when launched directly and when Blender launches it.

The same build runs in three ways, taking turns so that a machine that drifts affects each alike:

- `direct`: the Realtime Plane on its own, as `just rtp run` starts it;
- `blender`: Blender launches it through the extension and controls it while the stroke is drawn;
- `blender_stalled`: Blender launches it, then takes no host turn while the stroke is drawn.

Each run draws strokes into the Realtime Plane's window, stops the process, and reads the latency
report it writes at exit (`--latency-report`). Strokes come from `drawing_input`: synthetic pointer
events posted to the operating system (`--input synthetic`, macOS, needs permission to post events)
or a person (`--input person`).

Every run's buckets are merged per way, and the result is judged against `--budget`, which was
declared before this comparison ran:

- equivalence: for each stage, Blender's p50 and p99 may exceed the direct ones by at most the
  budget's relative margin plus its absolute margin;
- regression: on the hardware the budget was recorded on, the direct p50 and p99 may not exceed the
  limits derived from the baseline's own run-to-run spread;
- control: Blender's control to activation p99 may not exceed the budget.

`--output FILE` keeps every run's numbers and the environment. On other hardware, where the
regression limits are not judged, that file is the baseline a new budget is derived from. The test
skips (77) when synthetic input cannot be posted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile

from drawing_input import INPUTS, DrawingInput

HERE = Path(__file__).resolve().parent
SKIP = 77
WAYS = ("direct", "blender", "blender_stalled")
STAGES = ("input_to_executed", "executed_to_submitted", "input_to_submitted", "input_to_shown")
START_TIMEOUT_S = 30.0
SETTLE_S = 1.5


def _merge(reports: list[dict], stage: str) -> dict[int, int]:
    merged: dict[int, int] = {}
    for report in reports:
        for bound, count in report["stages_ns"][stage]["buckets"]:
            merged[bound] = merged.get(bound, 0) + count
    return merged


def _percentile(buckets: dict[int, int], fraction: float) -> int:
    """The bucket bound at `fraction` of the merged counts, as the Realtime Plane computes it."""
    total = sum(buckets.values())
    if total == 0:
        return 0
    rank = min(max(math.ceil(fraction * total), 1), total)
    seen = 0
    for bound in sorted(buckets):
        seen += buckets[bound]
        if seen >= rank:
            return bound
    return max(buckets)


def _summary(reports: list[dict]) -> dict:
    stages = {}
    for stage in (*STAGES, "offer_to_adoption"):
        merged = _merge(reports, stage)
        stages[stage] = {
            "count": sum(merged.values()),
            "p50_ns": _percentile(merged, 0.50),
            "p99_ns": _percentile(merged, 0.99),
            "runs_p50_ns": [report["stages_ns"][stage]["p50"] for report in reports],
            "runs_p99_ns": [report["stages_ns"][stage]["p99"] for report in reports],
            # Kept so a new budget can be derived again if how percentiles are taken changes.
            "runs_buckets": [report["stages_ns"][stage]["buckets"] for report in reports],
        }
    return stages


def _fingerprint(args: argparse.Namespace, display: dict) -> dict:
    def sysctl(name: str) -> str:
        found = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, check=False)
        return found.stdout.strip()

    return {
        "machine": sysctl("hw.model"),
        "processor": sysctl("machdep.cpu.brand_string"),
        "system": f"macOS {platform.mac_ver()[0]}" if sys.platform == "darwin" else platform.platform(),
        "display": display,
        "presentation": (
            "CAMetalLayer paced by CAMetalDisplayLink, newest frame each refresh (PresentTiming::AsSoonAsReady)"
        ),
        "input": args.device or args.drawing.Description,
        "build": args.build_type,
        "blender": args.blender_version,
    }


class Runner:
    """Runs one way at a time and collects what the Realtime Plane and Blender reported."""

    def __init__(self, args: argparse.Namespace, root: Path) -> None:
        self.args = args
        self.root = root
        self.packages = root / "packages"
        for wheel in sorted(args.wheel_dir.glob("*.whl")):
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(self.packages)
        self.drawing = args.drawing

    def _drawStrokes(self, window: int, seed: int) -> None:
        self.drawing.Draw(window, self.args.strokes, self.args.stroke_seconds, seed)

    def Run(self, way: str, index: int) -> tuple[dict, list[float]]:
        directory = self.root / f"{way}-{index}"
        directory.mkdir()
        report = directory / "latency.json"
        program = [str(self.args.realtime_plane), "--latency-report", str(report)]
        controls: list[float] = []
        if way == "direct":
            process = subprocess.Popen(program, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            time.sleep(SETTLE_S)
            self._drawStrokes(process.pid, index)
            process.send_signal(signal.SIGTERM)
            _, errors = process.communicate(timeout=START_TIMEOUT_S)
            if process.returncode != 0:
                raise RuntimeError(f"the Realtime Plane failed: {errors.decode(errors='replace')}")
        else:
            host = directory / "host.json"
            blender = subprocess.Popen(
                [
                    str(self.args.blender),
                    "--background",
                    "--factory-startup",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(HERE / "blender_realtime_plane_latency_host.py"),
                    "--",
                    "--extension-dir",
                    str(self.args.extension_dir.resolve()),
                    "--packages",
                    str(self.packages),
                    "--scope",
                    f"latency-{os.getpid()}-{way}-{index}",
                    "--state-dir",
                    str(directory / "state"),
                    "--output",
                    str(host),
                    *(["--stall"] if way == "blender_stalled" else []),
                    "--program",
                    *program,
                ],
                env={**os.environ, "FLEXIBLE_DRAWING_PROTOCOL_DIR": str(self.args.protocol_dir)},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            started = time.monotonic()
            while not (directory / "ready").exists():
                if blender.poll() is not None or time.monotonic() - started > START_TIMEOUT_S:
                    blender.kill()
                    raise RuntimeError(f"Blender opened no session: {blender.communicate()[0].decode()}")
                time.sleep(0.05)
            time.sleep(SETTLE_S)
            # The process Blender started, as its state file names it.
            state = json.loads((directory / "state" / "realtime_plane.json").read_text(encoding="utf-8"))
            self._drawStrokes(state["pid"], index)
            (directory / "finish").touch()
            output, _ = blender.communicate(timeout=START_TIMEOUT_S)
            if blender.returncode != 0 or not host.exists():
                raise RuntimeError(f"Blender failed:\n{output.decode(errors='replace')}")
            controls = json.loads(host.read_text(encoding="utf-8"))["control_to_activation_s"]
        return json.loads(report.read_text(encoding="utf-8")), controls


def _judge(budget: dict, summaries: dict, controls: list[float], fingerprint: dict) -> list[str]:
    failures = []
    equivalence = budget["equivalence"]
    for stage in equivalence["stages"]:
        for percentile in ("p50", "p99"):
            margin = equivalence[percentile]
            direct = summaries["direct"][stage][f"{percentile}_ns"]
            limit = direct * (1.0 + margin["relative"]) + margin["absolute_ns"]
            for way in ("blender", "blender_stalled"):
                measured = summaries[way][stage][f"{percentile}_ns"]
                if measured > limit:
                    failures.append(f"{way} {stage} {percentile} {measured} ns > {limit:.0f} ns (direct {direct} ns)")
    sameHardware = all(budget["fingerprint"].get(key) == fingerprint.get(key) for key in budget["regression_keys"])
    if sameHardware:
        for stage, limits in budget["regression"].items():
            for percentile, limit in limits.items():
                measured = summaries["direct"][stage][percentile]
                if measured > limit:
                    failures.append(f"direct {stage} {percentile} {measured} ns > baseline limit {limit} ns")
    else:
        print("regression limits not judged: the budget was recorded on other hardware", file=sys.stderr)
    if controls:
        ordered = sorted(controls)
        p99 = ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))]
        if p99 > budget["control_to_activation_p99_s"]:
            failures.append(f"control to activation p99 {p99:.4f} s > {budget['control_to_activation_p99_s']} s")
    else:
        failures.append("Blender timed no control to activation")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--realtime-plane", type=Path, required=True)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--blender-version", default="")
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--protocol-dir", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--build-type", default="")
    parser.add_argument("--input", choices=INPUTS, default="synthetic")
    parser.add_argument("--device", default="", help="what drew, when a person did: a pen's model, or a mouse")
    parser.add_argument("--runs", type=int, default=5, help="runs of each way")
    parser.add_argument("--strokes", type=int, default=6)
    parser.add_argument("--stroke-seconds", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=240.0, help="synthetic events per second")
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="where to keep this comparison's numbers")
    args = parser.parse_args()
    args.drawing = DrawingInput.Open(args.input, args.device, args.rate)
    if args.drawing is None:
        print("SKIP: posted pointer events reach no window: grant Accessibility, unlock the screen")
        return SKIP

    reports: dict[str, list[dict]] = {way: [] for way in WAYS}
    controls: list[float] = []
    with tempfile.TemporaryDirectory(prefix="realtime-plane-latency-") as directory:
        runner = Runner(args, Path(directory))
        for index in range(args.runs):
            for way in WAYS:
                report, timed = runner.Run(way, index)
                reports[way].append(report)
                controls.extend(timed if way == "blender" else [])
                print(
                    f"{way} run {index}: input_to_submitted p50 {report['stages_ns']['input_to_submitted']['p50']} "
                    f"p99 {report['stages_ns']['input_to_submitted']['p99']} ns",
                    flush=True,
                )
        shutil.rmtree(directory, ignore_errors=True)

    summaries = {way: _summary(reports[way]) for way in WAYS}
    fingerprint = _fingerprint(args, reports["direct"][0]["display"])
    result = {
        "fingerprint": fingerprint,
        "runs": args.runs,
        "ways": summaries,
        "control_to_activation_s": sorted(controls),
    }
    if args.output is not None:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({way: {s: summaries[way][s]["p50_ns"] for s in STAGES} for way in WAYS}))
    failures = _judge(json.loads(args.budget.read_text(encoding="utf-8")), summaries, controls, fingerprint)
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
