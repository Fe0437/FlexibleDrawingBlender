"""The C ABI in Python: one module per public header. Generated: do not edit.

Rendered by tools/abi/generate_python_binding.py from src/host/abi/manifest/abi_manifest.json.
Run `just abi-update` after a deliberate ABI change; `just abi-check` fails while this package and
the manifest disagree, and deletes nothing it did not write.

Every module here mirrors exactly one `public/flexible_drawing_<name>.h`, so it changes when that
header changes and for no other reason — the same split, and the same reasons, as the headers
themselves. `bootstrap` never changes; the interface modules churn.

Two layers, from one source. The `fd_*` declarations keep the C names unchanged, so every one can be
grepped against the header that promises it. Above them sit frozen value types — the same data, in
project naming, detached from the engine's memory — because a host holds a document identity long
after the call that produced it, and sometimes builds one from its own storage rather than from the
engine at all.

Field documentation is the header's own, carried across rather than restated, so a field is
explained in exactly one place. The behaviour that is decided rather than derived lives in the
hand-written modules beside this package.
"""

from __future__ import annotations

from .bootstrap import (
    BOOTSTRAP_PROTOTYPES,
    FD_ABI_VERSION,
    FD_ABI_VERSION_MAJOR,
    FD_ABI_VERSION_MAJOR_OF,
    FD_ABI_VERSION_MINOR,
    FD_ABI_VERSION_MINOR_OF,
    FD_ENGINE_STATUS_INCOMPATIBLE_ABI,
    FD_ENGINE_STATUS_INVALID_ARGUMENT,
    FD_ENGINE_STATUS_OK,
    FD_ENGINE_STATUS_UNKNOWN_INTERFACE,
    FD_LOG_SEVERITY_DEBUG,
    FD_LOG_SEVERITY_ERROR,
    FD_LOG_SEVERITY_INFO,
    FD_LOG_SEVERITY_TRACE,
    FD_LOG_SEVERITY_WARNING,
    fd_engine,
    fd_engine_status,
    fd_host_api,
    fd_log_callback,
)
from .document import (
    DocumentSnapshot,
    FD_DOCUMENT_MAX_LAYERS,
    FD_DOCUMENT_STATUS_UNKNOWN,
    FD_INTERFACE_DOCUMENT,
    FD_INTERFACE_DOCUMENT_VERSION,
    fd_document_api,
    fd_document_snapshot,
)
from .receiver import (
    FD_INTERFACE_RECEIVER,
    FD_INTERFACE_RECEIVER_VERSION,
    FD_RECEIVER_CONTACT_CANCELLED,
    FD_RECEIVER_CONTACT_FINISHED,
    FD_RECEIVER_INPUT_COALESCING,
    FD_RECEIVER_INPUT_CORRECTION,
    FD_RECEIVER_INPUT_ERASER,
    FD_RECEIVER_INPUT_HOVER,
    FD_RECEIVER_INPUT_PREDICTION,
    FD_RECEIVER_INPUT_PRESSURE,
    FD_RECEIVER_INPUT_TILT,
    FD_RECEIVER_INPUT_TIMESTAMP,
    FD_RECEIVER_INPUT_TWIST,
    FD_RECEIVER_MAX_COUNT,
    FD_RECEIVER_MAX_SAMPLES,
    FD_RECEIVER_ORIGIN_COALESCED,
    FD_RECEIVER_ORIGIN_CORRECTED,
    FD_RECEIVER_ORIGIN_MEASURED,
    FD_RECEIVER_ORIGIN_PREDICTED,
    FD_RECEIVER_STATUS_BUSY,
    FD_RECEIVER_STATUS_LIMIT,
    FD_RECEIVER_STATUS_NO_CONTACT,
    FD_RECEIVER_STATUS_OUT_OF_ORDER,
    FD_RECEIVER_STATUS_REJECTED,
    FD_RECEIVER_STATUS_UNKNOWN,
    InputSample,
    ReceiverDesc,
    ReceiverSnapshot,
    fd_input_batch,
    fd_input_sample,
    fd_receiver_api,
    fd_receiver_desc,
    fd_receiver_snapshot,
)

__all__ = [
    "BOOTSTRAP_PROTOTYPES",
    "DocumentSnapshot",
    "FD_ABI_VERSION",
    "FD_ABI_VERSION_MAJOR",
    "FD_ABI_VERSION_MAJOR_OF",
    "FD_ABI_VERSION_MINOR",
    "FD_ABI_VERSION_MINOR_OF",
    "FD_DOCUMENT_MAX_LAYERS",
    "FD_DOCUMENT_STATUS_UNKNOWN",
    "FD_ENGINE_STATUS_INCOMPATIBLE_ABI",
    "FD_ENGINE_STATUS_INVALID_ARGUMENT",
    "FD_ENGINE_STATUS_OK",
    "FD_ENGINE_STATUS_UNKNOWN_INTERFACE",
    "FD_INTERFACE_DOCUMENT",
    "FD_INTERFACE_DOCUMENT_VERSION",
    "FD_INTERFACE_RECEIVER",
    "FD_INTERFACE_RECEIVER_VERSION",
    "FD_LOG_SEVERITY_DEBUG",
    "FD_LOG_SEVERITY_ERROR",
    "FD_LOG_SEVERITY_INFO",
    "FD_LOG_SEVERITY_TRACE",
    "FD_LOG_SEVERITY_WARNING",
    "FD_RECEIVER_CONTACT_CANCELLED",
    "FD_RECEIVER_CONTACT_FINISHED",
    "FD_RECEIVER_INPUT_COALESCING",
    "FD_RECEIVER_INPUT_CORRECTION",
    "FD_RECEIVER_INPUT_ERASER",
    "FD_RECEIVER_INPUT_HOVER",
    "FD_RECEIVER_INPUT_PREDICTION",
    "FD_RECEIVER_INPUT_PRESSURE",
    "FD_RECEIVER_INPUT_TILT",
    "FD_RECEIVER_INPUT_TIMESTAMP",
    "FD_RECEIVER_INPUT_TWIST",
    "FD_RECEIVER_MAX_COUNT",
    "FD_RECEIVER_MAX_SAMPLES",
    "FD_RECEIVER_ORIGIN_COALESCED",
    "FD_RECEIVER_ORIGIN_CORRECTED",
    "FD_RECEIVER_ORIGIN_MEASURED",
    "FD_RECEIVER_ORIGIN_PREDICTED",
    "FD_RECEIVER_STATUS_BUSY",
    "FD_RECEIVER_STATUS_LIMIT",
    "FD_RECEIVER_STATUS_NO_CONTACT",
    "FD_RECEIVER_STATUS_OUT_OF_ORDER",
    "FD_RECEIVER_STATUS_REJECTED",
    "FD_RECEIVER_STATUS_UNKNOWN",
    "InputSample",
    "ReceiverDesc",
    "ReceiverSnapshot",
    "fd_document_api",
    "fd_document_snapshot",
    "fd_engine",
    "fd_engine_status",
    "fd_host_api",
    "fd_input_batch",
    "fd_input_sample",
    "fd_log_callback",
    "fd_receiver_api",
    "fd_receiver_desc",
    "fd_receiver_snapshot",
]
