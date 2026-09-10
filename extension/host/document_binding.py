"""Map native document identities to Blender-owned ID properties.

The engine hands out an identity; Blender owns where it is stored and how it survives a file save.
That split is the whole reason this module exists — the ABI never learns what a scene is.

The problem it solves: a .blend file outlives an engine. Save a file with a document open, quit, and
reopen it, and the scene still carries `document_id` 7 while the freshly created engine has never
issued one. `Synchronize` is what closes that gap, and it runs on every `register`:

```python
snapshot = document_binding.Synchronize(engine, bpy.context.scene)   # None if the scene has none
if snapshot is not None:
    print(snapshot.DocumentId, snapshot.Revision)
```

`Bind`, `Read`, and `Clear` are the raw accessors underneath it. `owner` is any Blender ID that
supports custom properties — a scene, an object, a collection — so what a document is attached to
stays the host's decision. A datablock deleted while still referenced raises `StaleBindingError`
rather than a bare Blender error, because that is a host bug and not an engine failure.
"""

from __future__ import annotations

from ..abi import FD_DOCUMENT_STATUS_UNKNOWN, DocumentSnapshot, EngineBridge, EngineError

DOCUMENT_ID = "flexible_drawing_document_id"
REVISION = "flexible_drawing_document_revision"
LAYER_COUNT = "flexible_drawing_document_layer_count"


class StaleBindingError(RuntimeError):
    """The Blender datablock holding a binding is gone, so nothing can be read or written."""


def Bind(owner: object, snapshot: DocumentSnapshot) -> None:
    """Write a document identity onto a Blender datablock, where a file save preserves it."""
    try:
        owner[DOCUMENT_ID] = snapshot.DocumentId
        owner[REVISION] = snapshot.Revision
        owner[LAYER_COUNT] = snapshot.LayerCount
    except (ReferenceError, TypeError) as error:
        raise StaleBindingError("Blender document owner is no longer available") from error


def Read(owner: object) -> DocumentSnapshot | None:
    """Read back a stored identity, or None when this datablock carries no document."""
    try:
        documentId = owner.get(DOCUMENT_ID)
        if documentId is None:
            return None
        return DocumentSnapshot(int(documentId), int(owner.get(REVISION, 0)), int(owner.get(LAYER_COUNT, 0)))
    except (ReferenceError, TypeError, ValueError) as error:
        raise StaleBindingError("Blender document owner is no longer available") from error


def Clear(owner: object) -> None:
    """Remove a stored identity, leaving the datablock as it was before any document."""
    try:
        for key in (DOCUMENT_ID, REVISION, LAYER_COUNT):
            if key in owner:
                del owner[key]
    except (ReferenceError, TypeError) as error:
        raise StaleBindingError("Blender document owner is no longer available") from error


def Synchronize(engine: EngineBridge, owner: object) -> DocumentSnapshot | None:
    """Reconcile a stored identity with the engine, restoring it if this engine never had it.

    A .blend file outlives an engine instance, so a binding read back from one names a document the
    freshly created engine has never heard of. That is the expected path, not a failure.
    """
    snapshot = Read(owner)
    if snapshot is None:
        return None
    try:
        current = engine.Documents.Query(snapshot.DocumentId)
    except EngineError as error:
        if error.Status != FD_DOCUMENT_STATUS_UNKNOWN:
            raise
        engine.Documents.Restore(snapshot)
        current = engine.Documents.Query(snapshot.DocumentId)
    Bind(owner, current)
    return current
