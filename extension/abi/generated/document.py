"""flexible_drawing_document.h in Python. Generated: do not edit — see this package's __init__.

The document interface: its table, its records, its constants, and its host values.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from .bootstrap import fd_engine, fd_engine_status


# Status codes
# Zero is success. The bootstrap owns 0-999; each interface owns a block from 1000 up.
FD_DOCUMENT_STATUS_UNKNOWN = 1000


# Limits
# Bounds the engine enforces on host-supplied sizes before they reach an allocator.
FD_DOCUMENT_MAX_LAYERS = 4096


# Interfaces
# Names and generations for fd_engine_get_interface.
FD_INTERFACE_DOCUMENT = "document"
FD_INTERFACE_DOCUMENT_VERSION = 1


class fd_document_snapshot(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("document_id", ctypes.c_uint64),
        ("revision", ctypes.c_uint64),
        ("layer_count", ctypes.c_uint64),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


class fd_document_api(ctypes.Structure):
    """Engine-owned table; struct_size reports how many entry points it populated."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        (
            "create",
            ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.c_char_p, ctypes.POINTER(fd_document_snapshot)),
        ),
        (
            "query",
            ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.c_uint64, ctypes.POINTER(fd_document_snapshot)),
        ),
        (
            "close",
            ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.c_uint64, ctypes.POINTER(fd_document_snapshot)),
        ),
        ("restore", ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.POINTER(fd_document_snapshot))),
    ]


@dataclass(frozen=True)
class DocumentSnapshot:
    """Host-side value of one `fd_document_snapshot`, detached from the engine's memory."""

    #: Stable identity of the document, unique within one engine and never reused. Note: Opaque: the value carries
    #: no structure and must not be parsed or ordered. Two engines may hand out the same number for unrelated
    #: documents.
    DocumentId: int
    #: Monotonic edit counter, starting at 1 and increasing on every change. Note: Compare for equality to detect
    #: that something changed. It is not a timestamp and the increment between two edits is unspecified.
    Revision: int
    #: Number of layers the document currently holds; at least 1.
    LayerCount: int

    @classmethod
    def FromRecord(cls, record: fd_document_snapshot) -> "DocumentSnapshot":
        """Copy an engine-filled record into an immutable host value."""
        return cls(int(record.document_id), int(record.revision), int(record.layer_count))

    def ToRecord(self) -> fd_document_snapshot:
        """Marshal this value into a fresh `fd_document_snapshot`, sized and ready to hand across."""
        return fd_document_snapshot(int(self.DocumentId), int(self.Revision), int(self.LayerCount))
