"""Probe Blender's bundled USD runtime and describe its registered Hydra delegates.

Blender ships its own build of USD. This module finds it and records the runtime and Hydra delegates
that build advertises. `host.hydra` separately owns Blender render-engine registration:

```python
fingerprint = ProbeBundledRuntime(bpy)
print(fingerprint.UsdVersion, [d.DisplayName for d in fingerprint.Delegates])
```

**Why it refuses a `pxr` Blender did not ship.** USD is a large C++ library with no stable ABI. A
second build of it reachable on `sys.path` — from a system install, a wheel, another add-on — would
load the same symbols twice into one process, which is a crash rather than a version mismatch.
`ProbeBundledRuntime` resolves the imported `pxr` and raises `CompatibilityError` unless it sits
under a directory `bpy.utils.resource_path` names, so the failure is a legible refusal at startup
instead of a hard crash later.

The `Digest` on a fingerprint is a stable hash of everything above, so a host can tell that the
runtime under it changed between sessions without comparing the parts by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path


@dataclass(frozen=True)
class DelegateDescriptor:
    """One Hydra render delegate the bundled USD runtime advertises."""

    PluginId: str
    DisplayName: str


@dataclass(frozen=True)
class CompatibilityFingerprint:
    """What the bundled runtime was, digested, so an incompatible upgrade is detectable."""

    BlenderVersion: str
    UsdVersion: str
    PxrRoot: str
    Delegates: tuple[DelegateDescriptor, ...]
    Digest: str


class CompatibilityError(RuntimeError):
    """Blender's bundled USD runtime is absent or is not the one Blender shipped."""


def ProbeBundledRuntime(bpy: object) -> CompatibilityFingerprint:
    """Fingerprint Blender's own USD runtime, refusing any pxr that Blender did not ship.

    A pxr from elsewhere on the path would be a different build of the same symbols loaded into one
    process, which is a crash rather than a version mismatch.
    """
    try:
        pxr = importlib.import_module("pxr")
        usd = importlib.import_module("pxr.Usd")
        imaging = importlib.import_module("pxr.UsdImagingGL")
    except (ImportError, ModuleNotFoundError) as error:
        raise CompatibilityError("Blender's bundled USD/Hydra Python runtime is unavailable") from error

    pxrRoot = str(Path(next(iter(pxr.__path__))).resolve())
    resourceRoots = tuple(Path(bpy.utils.resource_path(kind)).resolve() for kind in ("LOCAL", "SYSTEM"))
    resolvedPxr = Path(pxrRoot)
    if not any(root == resolvedPxr or root in resolvedPxr.parents for root in resourceRoots):
        raise CompatibilityError(f"refusing non-bundled USD runtime in Blender: {pxrRoot}")
    delegates = tuple(
        DelegateDescriptor(str(pluginId), str(imaging.Engine.GetRendererDisplayName(pluginId)))
        for pluginId in imaging.Engine.GetRendererPlugins()
    )
    payload = {
        "BlenderVersion": ".".join(str(part) for part in bpy.app.version),
        "Delegates": [{"DisplayName": item.DisplayName, "PluginId": item.PluginId} for item in delegates],
        "PxrRoot": pxrRoot,
        "UsdVersion": ".".join(str(part) for part in usd.GetVersion()),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return CompatibilityFingerprint(payload["BlenderVersion"], payload["UsdVersion"], pxrRoot, delegates, digest)
