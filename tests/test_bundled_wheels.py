#!/usr/bin/env python3
"""Bundle real Python wheels into the extension and check that Blender accepts the archive.

The extension will talk to the Realtime Plane through the iceoryx2 Python wheel, so its archive must
carry that wheel, its dependencies and their licence notices, and Blender's own validator must
accept the result. The wheel directory holds the wheels (``*.whl``); every other file in it is a
licence notice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import tomllib
import zipfile


def main() -> int:
    """Package the extension with the wheels, check the archive, then run Blender's validator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-script", type=Path, required=True)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSON file that records the validated package")
    args = parser.parse_args()

    wheels = sorted(args.wheel_dir.glob("*.whl"))
    notices = sorted(path for path in args.wheel_dir.iterdir() if path.is_file() and path.suffix != ".whl")
    if not wheels or not notices:
        parser.error(f"{args.wheel_dir} must hold the wheels and their licence notices")

    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "flexible_drawing.zip"
        subprocess.run(
            [
                sys.executable,
                str(args.package_script),
                "--extension",
                str(args.extension_dir.resolve()),
                "--library",
                str(args.library),
                "--output",
                str(archive),
                *[item for wheel in wheels for item in ("--wheel", str(wheel))],
                *[item for notice in notices for item in ("--third-party-notice", str(notice))],
            ],
            check=True,
        )
        with zipfile.ZipFile(archive) as contents:
            names = set(contents.namelist())
            manifest = tomllib.loads(contents.read("flexible_drawing/blender_manifest.toml").decode("utf-8"))
        missing = [f"flexible_drawing/wheels/{wheel.name}" for wheel in wheels] + [
            f"flexible_drawing/third_party/{notice.name}" for notice in notices
        ]
        missing = [name for name in missing if name not in names]
        if missing:
            print(f"the archive lacks {missing}", file=sys.stderr)
            return 1
        if manifest.get("wheels") != [f"./wheels/{wheel.name}" for wheel in wheels]:
            print(f"the manifest declares {manifest.get('wheels')}", file=sys.stderr)
            return 1
        validate = subprocess.run(
            [
                str(args.blender),
                "--background",
                "--factory-startup",
                "--command",
                "extension",
                "validate",
                str(archive),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if validate.returncode != 0:
            print(f"Blender refused the archive:\n{validate.stdout}{validate.stderr}", file=sys.stderr)
            return 1
        archive_bytes = archive.stat().st_size
        evidence = {
            "archive_bytes": archive_bytes,
            "machine": platform.machine(),
            "platform": platform.platform(),
            "third_party_notice_names": [notice.name for notice in notices],
            "validation": "passed",
            "wheel_names": [wheel.name for wheel in wheels],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Blender accepted {archive_bytes} bytes with {len(wheels)} wheels; evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
