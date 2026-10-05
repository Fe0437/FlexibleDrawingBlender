"""The host-neutral half of the Blender extension: the C ABI, and nothing about Blender.

Nothing in this package imports `bpy`, which is what lets it be tested without Blender and reused by
another Python host unchanged. The layering matches the engine's own `src/host/abi`:

| Module          | Holds                                                          | Changes            |
| --------------- | -------------------------------------------------------------- | ------------------ |
| `generated`     | the C headers transliterated into ctypes — generated, not edited | every ABI change   |
| `errors`        | `EngineError`                                                  | never              |
| `library`       | finding and loading the shared library                         | never              |
| `registry`      | finds the interface wrappers, so no list is kept by hand       | never              |
| `engine`        | opening and shutting down an engine, and checking versions     | never              |
| `reflected`     | decoding the engine's self-describing values by name           | when the format does |
| `interfaces/`   | one module per engine interface — **new interfaces go here**   | often              |

The records, the constants, and the frozen value types a host holds, such as `DocumentSnapshot`, are
all generated from the headers, field documentation included.
Only behaviour is written by hand.

Adding an interface means one new module in `interfaces/`. Nothing else changes: `registry` finds
it and the engine publishes it under the name the module gives.
The full walkthrough, both sides of the boundary, is in `src/host/abi/README.md`.

FD_* names are re-exported from `generated` unchanged, so any constant a host compares against can
be grepped straight to the header that promises it.
"""

from __future__ import annotations

from . import generated
from .engine import EngineBridge, LogSink
from .errors import EngineError
from .generated import (
    FD_ABI_VERSION,
    FD_ABI_VERSION_MAJOR,
    FD_ABI_VERSION_MINOR,
    FD_DOCUMENT_MAX_LAYERS,
    FD_DOCUMENT_STATUS_UNKNOWN,
    FD_ENGINE_STATUS_INCOMPATIBLE_ABI,
    FD_ENGINE_STATUS_INVALID_ARGUMENT,
    FD_ENGINE_STATUS_OK,
    FD_ENGINE_STATUS_UNKNOWN_INTERFACE,
    FD_LOG_SEVERITY_DEBUG,
    FD_LOG_SEVERITY_ERROR,
    FD_LOG_SEVERITY_INFO,
    FD_LOG_SEVERITY_TRACE,
    FD_LOG_SEVERITY_WARNING,
    FD_UI_SCHEMA_STATUS_UNRESOLVED,
    DocumentSnapshot,
)
from .interfaces.document import DocumentInterface
from .interfaces.ui_schema import UiSchema, UiSchemaInterface
from .library import LIBRARY_OVERRIDE, DiscoverLibrary, LibraryName, LoadLibrary
from .reflected import Decode, Record

__all__ = [
    "FD_ABI_VERSION",
    "FD_ABI_VERSION_MAJOR",
    "FD_ABI_VERSION_MINOR",
    "FD_DOCUMENT_MAX_LAYERS",
    "FD_DOCUMENT_STATUS_UNKNOWN",
    "FD_ENGINE_STATUS_INCOMPATIBLE_ABI",
    "FD_ENGINE_STATUS_INVALID_ARGUMENT",
    "FD_ENGINE_STATUS_OK",
    "FD_ENGINE_STATUS_UNKNOWN_INTERFACE",
    "FD_LOG_SEVERITY_DEBUG",
    "FD_LOG_SEVERITY_ERROR",
    "FD_LOG_SEVERITY_INFO",
    "FD_LOG_SEVERITY_TRACE",
    "FD_LOG_SEVERITY_WARNING",
    "FD_UI_SCHEMA_STATUS_UNRESOLVED",
    "LIBRARY_OVERRIDE",
    "Decode",
    "DiscoverLibrary",
    "DocumentInterface",
    "DocumentSnapshot",
    "EngineBridge",
    "EngineError",
    "LibraryName",
    "LoadLibrary",
    "LogSink",
    "Record",
    "UiSchema",
    "UiSchemaInterface",
    "generated",
]
