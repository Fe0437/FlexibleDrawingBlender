"""Blender extension bootstrap: the add-on entry points Blender itself calls.

`register` and `unregister` are named by Blender, not by the project. This module is only the
composition root: it owns the one live engine, wires the engine's diagnostics into Python logging,
and starts and stops everything in an order that is exactly mirrored. It holds no drawing logic.

What lives where, and which way the dependencies point:

    __init__          composition: owns the engine, registers and unregisters everything
      ├── presentation/     operators and panels registered with Blender
      ├── host/             document, receiver, input, viewport, geometry, USD, and Hydra bindings
      └── abi/              the host-neutral native-engine client; never imports bpy

Only this composition root and modules above `abi/` may depend on Blender. `abi/` is host-neutral,
which lets it be tested without Blender and reused by another Python host unchanged.

See README.md beside this file for the quick start and a worked example.
"""

from __future__ import annotations

import logging
from pathlib import Path
import tomllib

import bpy

from . import presentation as _presentation
from .abi import (
    FD_LOG_SEVERITY_DEBUG,
    FD_LOG_SEVERITY_ERROR,
    FD_LOG_SEVERITY_INFO,
    FD_LOG_SEVERITY_TRACE,
    FD_LOG_SEVERITY_WARNING,
    EngineBridge,
    EngineError,
)
from .host import document_binding as _documentBinding
from .host import hydra as _hydra
from .host import receiver_binding as _receiverBinding

# The one live engine, owned here for the extension's lifetime. Presentation is lent a reference
# and gives it back on unregister, so exactly one module decides when the engine exists.
_engine: EngineBridge | None = None
# Whether Blender itself hosts a painting receiver, which is what makes the paint tool exist.
#
# True today, because Blender's own editors are the only canvas there is. When the Realtime Plane
# arrives it owns its native input, and a Blender canvas becomes one choice among several; a
# deployment that only drives the external canvas sets this False and gets no paint tool, rather
# than a tool that would send pen events nothing asked for.
_IN_PROCESS_RECEIVER_SELECTED = True
# Published into Blender's driver namespace so a .blend, a script, or a support request can read
# which engine build is loaded without importing anything.
_namespaceKey = "flexible_drawing_engine_version"
_hydraClasses: tuple[type, ...] = ()
_hydraFingerprint: _hydra.CompatibilityFingerprint | None = None
_logger = logging.getLogger("flexible_drawing")
_logHandler: logging.Handler | None = None

# The engine's severities named rather than numbered, so a new one cannot be silently mismapped.
_LOG_LEVELS = {
    FD_LOG_SEVERITY_TRACE: logging.DEBUG,
    FD_LOG_SEVERITY_DEBUG: logging.DEBUG,
    FD_LOG_SEVERITY_INFO: logging.INFO,
    FD_LOG_SEVERITY_WARNING: logging.WARNING,
    FD_LOG_SEVERITY_ERROR: logging.ERROR,
}


def _parseVersion(version: str) -> tuple[int, int, int]:
    parts = tuple(int(part) for part in version.split("."))
    if len(parts) != 3:
        raise EngineError(None, f"Blender manifest version must have three components: {version}")
    return parts


def _blenderVersionRange() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    manifest = tomllib.loads(Path(__file__).with_name("blender_manifest.toml").read_text(encoding="utf-8"))
    return _parseVersion(manifest["blender_version_min"]), _parseVersion(manifest["blender_version_max"])


def _enableLogging() -> None:
    global _logHandler
    if _logHandler is not None:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[Flexible Drawing] %(levelname)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False
    _logHandler = handler


def _disableLogging() -> None:
    global _logHandler
    if _logHandler is not None:
        _logger.removeHandler(_logHandler)
        _logHandler.close()
        _logHandler = None


def _nativeLog(severity: int, category: str, message: str) -> None:
    _logger.log(_LOG_LEVELS.get(severity, logging.INFO), "[%s] %s", category, message)


def register() -> None:
    """Start the extension: Blender calls this when the add-on is enabled.

    The order matters. The engine is opened first, because everything else needs it;
    documents are reconciled next, because a .blend opened before the add-on was enabled already
    carries identities this engine has never heard of; the UI registers last, so no operator can
    become clickable before the engine behind it exists.

    Failure at any point unwinds everything already started and re-raises, leaving Blender with no
    half-registered extension. Calling it twice is a no-op, which is what makes enable/disable
    cycles safe.
    """
    global _engine, _hydraClasses, _hydraFingerprint
    if _engine is not None:
        return
    minimumVersion, maximumVersion = _blenderVersionRange()
    if not minimumVersion <= tuple(bpy.app.version) < maximumVersion:
        version = ".".join(str(part) for part in bpy.app.version)
        supported = f">={'.'.join(map(str, minimumVersion))},<{'.'.join(map(str, maximumVersion))}"
        raise EngineError(None, f"Flexible Drawing requires Blender {supported}; found {version}")
    _enableLogging()
    try:
        engine = EngineBridge.Open(log=_nativeLog)
    except Exception:
        _logger.exception("[blender] native engine startup failed")
        _disableLogging()
        raise
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            _documentBinding.Synchronize(engine, scene)
        _hydraFingerprint, _hydraClasses = _hydra.RegisterAvailableEngines(bpy)
        _presentation.SetEngine(engine)
        _presentation.SelectInProcessReceiver(_IN_PROCESS_RECEIVER_SELECTED)
        _presentation.register()
    except Exception:
        _hydra.UnregisterEngines(bpy, _hydraClasses)
        _hydraClasses = ()
        _hydraFingerprint = None
        _presentation.SelectInProcessReceiver(False)
        _presentation.SetEngine(None)
        engine.Shutdown()
        _logger.exception("[blender] extension registration failed")
        _disableLogging()
        raise
    bpy.app.driver_namespace[_namespaceKey] = engine.Version()
    _engine = engine
    _logger.info("[blender] extension registered; engine version %s", engine.Version())


def unregister() -> None:
    """Stop the extension: Blender calls this when the add-on is disabled or Blender quits.

    The exact mirror of `register`, in reverse, and every step runs even if an earlier one raises —
    a class left registered would outlive the engine it calls, and the next enable would fail on a
    name Blender still holds. Safe to call when registration never completed.
    """
    global _engine, _hydraClasses, _hydraFingerprint
    if _engine is None:
        _presentation.SetEngine(None)
        bpy.app.driver_namespace.pop(_namespaceKey, None)
        _disableLogging()
        return
    try:
        try:
            _presentation.unregister()
        finally:
            _hydra.UnregisterEngines(bpy, _hydraClasses)
            _hydraClasses = ()
            _hydraFingerprint = None
            _presentation.SelectInProcessReceiver(False)
            _presentation.SetEngine(None)
            # Receivers die with the engine either way; closing them first keeps shutdown the exact
            # mirror of what opened them.
            _receiverBinding.CloseAll(_engine)
            _engine.Shutdown()
    finally:
        bpy.app.driver_namespace.pop(_namespaceKey, None)
        _engine = None
        _logger.info("[blender] extension unregistered")
        _disableLogging()
