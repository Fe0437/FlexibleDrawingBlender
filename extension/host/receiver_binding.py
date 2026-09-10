"""Keep track of the in-process painting receiver each Blender scene paints into.

A receiver is a live engine session, not a document. Its identity means nothing to another engine
and nothing after this one shuts down, so it is held here for the extension's lifetime rather than
written onto the scene: a `.blend` that carried one would reopen holding a number no engine
recognises. What does persist is the document, and `document_binding` owns that.

One receiver per scene. Opening a second for the same scene would give the same canvas two sets of
committed tiles, and neither would be the whole picture.

This module only decides which receiver a scene uses. Capturing input, running graphs and writing
tiles are the receiver's own business, on the engine's side of the boundary.
"""

from __future__ import annotations

from ..abi import FD_RECEIVER_INPUT_COALESCING, FD_RECEIVER_INPUT_PRESSURE, FD_RECEIVER_INPUT_TIMESTAMP

#: What Blender's event loop actually produces, for the receiver's capability tier.
#:
#: Pressure, because a tablet reports it. Coalescing, because Blender delivers the positions it
#: could not send individually. Timestamp, because the operator records every observation from a
#: monotonic clock. Not prediction or correction: Blender does not guess where the pen is going,
#: and a capability claimed here that Blender cannot deliver would admit a tool that then behaves
#: wrongly.
BLENDER_INPUT_CAPABILITIES = FD_RECEIVER_INPUT_PRESSURE | FD_RECEIVER_INPUT_COALESCING | FD_RECEIVER_INPUT_TIMESTAMP

#: Width and height of one canvas tile, in canvas units.
#:
#: Provisional: the engine does not report a tile size, so the host picks the granularity it wants
#: changes reported at. When the engine reports it, it comes from the document. Nothing may treat
#: this number as a picture size.
TILE_EXTENT = 64

#: Largest run a Blender stroke will submit at once. Blender delivers far fewer per redraw; the
#: bound is what the receiver reserves for, so a run beyond it is refused rather than allocated for.
MAXIMUM_BATCH_SAMPLES = 1024

_receivers: dict[str, int] = {}


def Bind(engine: object, scene: object) -> int:
    """The scene's receiver, opening one the first time the scene is painted into."""
    existing = _receivers.get(scene.name)
    if existing is not None:
        return existing
    snapshot = engine.Receivers.Create(
        seed=_seedFor(scene),
        tileExtent=TILE_EXTENT,
        maximumBatchSamples=MAXIMUM_BATCH_SAMPLES,
        inputCapabilities=BLENDER_INPUT_CAPABILITIES,
    )
    _receivers[scene.name] = snapshot.ReceiverId
    return snapshot.ReceiverId


def Read(scene: object) -> int | None:
    """The scene's receiver, or None when nothing has painted into it yet."""
    return _receivers.get(scene.name)


def Close(engine: object, scene: object) -> None:
    """Close the scene's receiver, if it has one."""
    receiverId = _receivers.pop(scene.name, None)
    if receiverId is not None:
        engine.Receivers.Close(receiverId)


def CloseAll(engine: object) -> None:
    """Close every receiver this extension opened. The composition root calls this on shutdown."""
    for receiverId in _receivers.values():
        engine.Receivers.Close(receiverId)
    _receivers.clear()


def _seedFor(scene: object) -> int:
    """The replay seed the scene's receiver holds for its whole life.

    Provisional: a seed is not saved with the document yet, so a reopened document cannot reproduce
    the brush variation this produced. When the document carries one, it comes from there.
    """
    return 1 + (len(_receivers) * 2)
