"""Expose delegates from the verified bundled USD runtime through Blender's Hydra API.

USD runtime compatibility is owned by `host.usd`; this module owns only the Blender class
registration lifecycle. Keeping those reasons to change separate mirrors the native
`host.blender.usd` and `host.blender.hydra` boundaries.
"""

from __future__ import annotations

from .usd import CompatibilityFingerprint, ProbeBundledRuntime


def RegisterAvailableEngines(bpy: object) -> tuple[CompatibilityFingerprint | None, tuple[type, ...]]:
    """Register one render engine per advertised delegate, or nothing when Hydra is unavailable."""
    if not hasattr(bpy.types, "HydraRenderEngine"):
        return None, ()
    fingerprint = ProbeBundledRuntime(bpy)
    classes: list[type] = []
    for index, delegate in enumerate(fingerprint.Delegates):
        engineClass = type(
            f"FLEXIBLE_DRAWING_HYDRA_ENGINE_{index}",
            (bpy.types.HydraRenderEngine,),
            {
                "bl_idname": f"FLEXIBLE_DRAWING_HYDRA_{index}",
                "bl_label": f"Flexible Drawing — {delegate.DisplayName}",
                "bl_use_preview": True,
                "bl_delegate_id": delegate.PluginId,
            },
        )
        bpy.utils.register_class(engineClass)
        classes.append(engineClass)
    return fingerprint, tuple(classes)


def UnregisterEngines(bpy: object, classes: tuple[type, ...]) -> None:
    """Unregister engines in reverse order, so registration and teardown are exact mirrors."""
    for engineClass in reversed(classes):
        bpy.utils.unregister_class(engineClass)
