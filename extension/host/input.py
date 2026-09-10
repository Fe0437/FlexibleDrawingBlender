"""Turn captured Blender pen and mouse events into engine samples.

Blender describes an event one way and the engine another. This module converts between them,
writing each sample straight into the batch the engine will read, so nothing is built and copied in
between. The events are captured elsewhere and arrive here as plain dictionaries, so this module
does not need `bpy` and can be tested on its own:

```python
batch = engine.Receivers.Batch()
AppendHostEvents(batch, [
    {"x": 12.0, "y": 4.0, "pressure": 0.5, "time_nanoseconds": 1, "sequence": 1, "origin": "MEASURED"},
    {"x": 18.0, "y": 4.5, "pressure": 0.6, "time_nanoseconds": 2, "sequence": 2, "origin": "PREDICTED"},
])
result = engine.Receivers.Submit(receiverId, contactId, ordinal, batch)
```

Get `origin` right. The engine keeps measured and coalesced points, but treats predicted points as
guesses and redraws them once the real ones arrive. If you label a predicted point as measured, the
engine can never correct it. That is why the names are written out here instead of passed through as
numbers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..abi import (
    FD_RECEIVER_ORIGIN_COALESCED,
    FD_RECEIVER_ORIGIN_CORRECTED,
    FD_RECEIVER_ORIGIN_MEASURED,
    FD_RECEIVER_ORIGIN_PREDICTED,
    InputBatch,
)

# Names the engine's exported FD_RECEIVER_ORIGIN_* values rather than repeating the numbers.
_ORIGINS = {
    "MEASURED": FD_RECEIVER_ORIGIN_MEASURED,
    "COALESCED": FD_RECEIVER_ORIGIN_COALESCED,
    "PREDICTED": FD_RECEIVER_ORIGIN_PREDICTED,
    "CORRECTED": FD_RECEIVER_ORIGIN_CORRECTED,
}

#: Blender's pointer-motion event types, and what each one is worth to the engine.
#:
#: A tablet reports positions far faster than Blender redraws. Blender keeps the ones it could not
#: deliver individually and sends them as `INBETWEEN_MOUSEMOVE` events, just before the `MOUSEMOVE`
#: they lead up to, which is exactly what the engine calls a coalesced sample. A mouse produces few
#: or none of them.
#:
#: Nothing here maps to `PREDICTED` or `CORRECTED`. Blender does not guess where the pen is going,
#: so a predicted sample — and the corrected one that would replace it — can only come from a
#: predictor this project runs itself.
MOTION_EVENT_ORIGINS = {
    "MOUSEMOVE": "MEASURED",
    "INBETWEEN_MOUSEMOVE": "COALESCED",
}


def HostEventFromPointer(
    event: object, position: tuple[float, float], sequence: int, timeNanoseconds: int, origin: str
) -> dict[str, object]:
    """Describe one Blender pointer event the way `AppendHostEvents` reads it.

    `position` is the event's pointer position already in canvas units. Which editor the pointer was
    in, and how that editor maps onto the canvas, is `host.viewport`'s to know, not this module's.

    The caller supplies `origin` because Blender says what kind of event it delivered, not what the
    sample is worth: `MOTION_EVENT_ORIGINS` translates a motion event's type, and the press that
    starts a stroke is a measured position without being a motion event at all.

    A mouse has no pressure. Blender reports 1.0 for one, which is also what a pen pressed flat
    reports, so `is_tablet` is the only thing separating them and pressure is read from the event
    only when a tablet sent it.
    """
    x, y = position
    return {
        "x": x,
        "y": y,
        "pressure": float(event.pressure) if event.is_tablet else 1.0,
        "time_nanoseconds": timeNanoseconds,
        "sequence": sequence,
        "origin": origin,
    }


def AppendHostEvent(batch: InputBatch, event: Mapping[str, object]) -> None:
    """Add one captured Blender event, rejecting anything the engine will not accept.

    Checking here rather than at the boundary keeps the failure readable: the engine can only say
    that a batch was invalid, while this can name the field.
    """
    origin = str(event["origin"]).upper()
    if origin not in _ORIGINS:
        raise ValueError(f"unsupported Blender input origin: {origin}")
    pressure = float(event["pressure"])
    if not 0.0 <= pressure <= 1.0:
        raise ValueError("Blender input pressure must be in [0, 1]")
    batch.Append(
        x=float(event["x"]),
        y=float(event["y"]),
        pressure=pressure,
        timeNanoseconds=int(event["time_nanoseconds"]),
        sequence=int(event["sequence"]),
        origin=_ORIGINS[origin],
    )


def AppendHostEvents(batch: InputBatch, events: Iterable[Mapping[str, object]]) -> None:
    """Add captured Blender events to a batch in their delivered order."""
    for event in events:
        AppendHostEvent(batch, event)
