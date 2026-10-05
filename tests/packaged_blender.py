"""Package the extension and install it into a throwaway Blender profile, as a person installs it.

Checks that run Blender against the extension a person would get share this: it packages the
extension with its wheels, and the real Realtime Plane when a build directory is given, installs the
package into a profile of its own under `root`, and returns the environment that makes Blender use
that profile and a Realtime Plane scope no person's canvas uses. `StopLeftovers` ends whatever
Realtime Plane a failed run left in that scope.

```python
environment = Install(root, args, scope, buildDir=args.build_dir)
subprocess.run([str(args.blender), "--background", "--python", script], env=environment)
StopLeftovers(root, scope)
```
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import types

#: Where the installed extension lives inside the throwaway profile.
INSTALLED = "extensions/user_default/flexible_drawing"
#: The module Blender loads the installed extension as.
MODULE = "bl_ext.user_default.flexible_drawing"


def Install(root: Path, args: object, scope: str, buildDir: Path | None = None) -> dict[str, str]:
    """Package and install the extension under `root`; return the environment that uses it.

    `args` carries `blender`, `package_script`, `extension_dir`, `library` and `wheel_dir`. With
    `buildDir`, the package carries the real Realtime Plane installed from that build.
    """
    bundle: list[str] = []
    if buildDir is not None:
        install = ["cmake", "--install", str(buildDir), "--component", "realtime_plane"]
        subprocess.run([*install, "--prefix", str(root / "realtime-plane")], check=True, capture_output=True)
        bundle = ["--realtime-plane-dir", str(root / "realtime-plane")]
    subprocess.run(
        [
            sys.executable,
            str(args.package_script),
            "--extension",
            str(args.extension_dir.resolve()),
            "--library",
            str(args.library),
            "--wheel-dir",
            str(args.wheel_dir),
            *bundle,
            "--output",
            str(root / "flexible_drawing.zip"),
        ],
        check=True,
        capture_output=True,
    )
    environment = {
        **os.environ,
        "BLENDER_USER_CONFIG": str(root / "config"),
        "BLENDER_USER_SCRIPTS": str(root / "scripts"),
        "BLENDER_USER_EXTENSIONS": str(root / "extensions"),
        "BLENDER_USER_DATAFILES": str(root / "datafiles"),
        "FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE": scope,
    }
    environment.pop("FLEXIBLE_DRAWING_PROTOCOL_DIR", None)  # the package carries its own profile
    installed = subprocess.run(
        [
            str(args.blender),
            "--background",
            "--factory-startup",
            "--command",
            "extension",
            "install-file",
            "-r",
            "user_default",
            "-e",
            str(root / "flexible_drawing.zip"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if installed.returncode != 0:
        raise RuntimeError(f"Blender did not install the extension:\n{installed.stdout}{installed.stderr}")
    return environment


def RealtimePlaneLog(root: Path, scope: str) -> str:
    """What the scope's Realtime Plane printed, for a failure report; empty when it left no log."""
    _loadClient(root)
    from flexible_drawing.realtime_plane import process

    path = process.StateDirectory(scope) / "realtime_plane.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def RealtimePlanePid(root: Path, scope: str) -> int:
    """The process of the scope's running Realtime Plane, as its state file names it."""
    _loadClient(root)
    from flexible_drawing.realtime_plane import process

    running = process.Attach(process.StateDirectory(scope))
    if running is None:
        raise RuntimeError(f"no Realtime Plane is running in scope {scope}")
    return running.Pid


def _loadClient(root: Path) -> None:
    package = types.ModuleType("flexible_drawing")
    package.__path__ = [str(root / INSTALLED)]
    sys.modules["flexible_drawing"] = package


def StopLeftovers(root: Path, scope: str) -> None:
    """End a Realtime Plane a failed run left behind in its scope, and forget the scope."""
    _loadClient(root)
    from flexible_drawing.realtime_plane import process

    running = process.Attach(process.StateDirectory(scope))
    if running is not None:
        running.Stop()
    shutil.rmtree(process.StateDirectory(scope), ignore_errors=True)
