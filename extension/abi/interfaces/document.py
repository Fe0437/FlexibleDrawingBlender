"""The document lifecycle interface, mirroring flexible_drawing_document.h.

Wraps `fd_document_api`. Nothing Blender-specific belongs here: the host decides where a document
identity is stored, this module only moves it across the boundary. `DocumentSnapshot`, the value it
deals in, is generated from the same header — see `generated`.
"""

from __future__ import annotations

import ctypes

from ..generated import (
    FD_INTERFACE_DOCUMENT,
    FD_INTERFACE_DOCUMENT_VERSION,
    DocumentSnapshot,
    fd_document_api,
    fd_document_snapshot,
)
from . import Interface


class DocumentInterface(Interface):
    """Create, query, close, and restore drawing documents."""

    NAME = FD_INTERFACE_DOCUMENT
    VERSION = FD_INTERFACE_DOCUMENT_VERSION
    TABLE = fd_document_api
    ATTRIBUTE = "Documents"

    def _snapshot(self, entryPoint: object, *arguments: object) -> DocumentSnapshot:
        """Run one call that fills a snapshot, and detach the result from the engine's record."""
        # struct_size is stamped by the generated constructor, so it cannot be forgotten here.
        record = fd_document_snapshot()
        self._invoke(entryPoint, *arguments, ctypes.byref(record))
        return DocumentSnapshot.FromRecord(record)

    def Create(self, name: str) -> DocumentSnapshot:
        """Create a document and return its identity."""
        return self._snapshot(self._entry("create"), name.encode("utf-8"))

    def Query(self, documentId: int) -> DocumentSnapshot:
        """Read an active document's current identity.

        Raises EngineError with FD_DOCUMENT_STATUS_UNKNOWN when the engine has no such document,
        which is how a host detects that a persisted identity needs restoring.
        """
        return self._snapshot(self._entry("query"), documentId)

    def Close(self, documentId: int) -> DocumentSnapshot:
        """Close an active document and return its final identity."""
        return self._snapshot(self._entry("close"), documentId)

    def Restore(self, snapshot: DocumentSnapshot) -> None:
        """Restore a persisted identity into this engine, as after loading a host file."""
        # Bound to a local so the record outlives the pointer handed across, not just the argument.
        record = snapshot.ToRecord()
        self._invoke(self._entry("restore"), ctypes.byref(record))
