"""Find the native engine on disk and load it with every exported prototype applied.

This is the only module that knows about platforms, file names, and environment overrides. It stops
at a loaded `ctypes.CDLL`: negotiating a version and creating an engine is `engine.py`'s job.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import platform

from .errors import EngineError
from .generated import BOOTSTRAP_PROTOTYPES

# The engine ships beside the extension, under native/. Set this to point at a build tree instead.
LIBRARY_OVERRIDE = "FLEXIBLE_DRAWING_ENGINE_LIBRARY"

_LIBRARY_NAMES = {
    "Windows": "flexible_drawing_engine.dll",
    "Darwin": "libflexible_drawing_engine.dylib",
}
_DEFAULT_LIBRARY_NAME = "libflexible_drawing_engine.so"


def LibraryName() -> str:
    """Name the shared library carries on this platform."""
    return _LIBRARY_NAMES.get(platform.system(), _DEFAULT_LIBRARY_NAME)


def DiscoverLibrary(extensionRoot: Path) -> Path:
    """Locate the native engine, preferring an explicit override over the packaged copy.

    A packaged extension carries the engine at `native/<platform name>`. During development, point
    FLEXIBLE_DRAWING_ENGINE_LIBRARY at a build tree instead, so an edit-and-rebuild cycle needs no
    repackaging:

    ```sh
    export FLEXIBLE_DRAWING_ENGINE_LIBRARY=build/debug/src/host/abi/libflexible_drawing_engine.dylib
    ```

    Raises EngineError with a Status of None when neither exists — a host-side failure, since no
    call was ever made.
    """
    explicit = os.environ.get(LIBRARY_OVERRIDE)
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not path.is_file():
            raise EngineError(None, f"{LIBRARY_OVERRIDE} does not exist: {path}")
        return path
    candidate = extensionRoot / "native" / LibraryName()
    if not candidate.is_file():
        raise EngineError(None, f"Flexible Drawing native engine is missing: {candidate}")
    return candidate


def LoadLibrary(path: Path) -> ctypes.CDLL:
    """Load the engine and prototype the whole frozen bootstrap.

    Every exported function is prototyped from the generated table rather than at its call site,
    because an unprototyped ctypes call marshals arguments and the result as C `int` — which
    silently truncates a pointer on a 64-bit target instead of failing.
    """
    library = ctypes.CDLL(str(path))
    for name, (returns, arguments) in BOOTSTRAP_PROTOTYPES.items():
        entryPoint = getattr(library, name)
        entryPoint.restype = returns
        entryPoint.argtypes = arguments
    return library
