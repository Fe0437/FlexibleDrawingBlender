"""The one failure type the boundary reports, so a host has a single thing to catch."""

from __future__ import annotations


class EngineError(RuntimeError):
    """A native-engine failure carrying the status the boundary returned.

    `Status` is one of the FD_*_STATUS_* values in `generated`, or None when the failure happened on
    the host side of the boundary and no call was ever made — a missing library, an engine that was
    never initialized. Callers that recover from a specific failure compare against the generated
    constant rather than the number, as `document_binding` does with FD_DOCUMENT_STATUS_UNKNOWN.

    Recovering from one specific failure, as `document_binding.Synchronize` does:

    ```python
    try:
        snapshot = engine.Documents.Query(documentId)
    except EngineError as error:
        if error.Status != FD_DOCUMENT_STATUS_UNKNOWN:
            raise
        engine.Documents.Restore(stored)
    ```
    """

    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.Status = status
