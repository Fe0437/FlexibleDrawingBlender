"""Drive one engine receiver from captured Blender pointer events.

This is Blender's input source: it owns a contact from press to release, collects the events that
arrive in between, and submits them in bounded runs. Deciding when a run is complete is Blender's
business, not the engine's — a fast tablet's extra positions arrive as `INBETWEEN_MOUSEMOVE` events
followed by the `MOUSEMOVE` they lead up to, so the measured event ends a run.

The events arrive as plain dictionaries from `input.HostEventFromPointer`, so this module needs no
`bpy` and is tested without Blender:

```python
source = InputSourceOnBlender(engine, receiverId, contactId=1, maximumBatchSamples=1024)
source.Begin()
source.Collect({"x": 12.0, "y": 4.0, "pressure": 0.5, "time_nanoseconds": 1, "sequence": 1,
                "origin": "MEASURED"})
source.Submit()
source.Finish()
```

It is one of several sources the same receiver contract accepts, and it is the only one Blender
provides. A receiver running outside Blender never sees a Blender event, which is why nothing here
reaches back into the operator that owns it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..abi import (
    FD_RECEIVER_CONTACT_CANCELLED,
    FD_RECEIVER_CONTACT_FINISHED,
    FD_RECEIVER_STATUS_BUSY,
    EngineError,
    ReceiverSnapshot,
)
from .input import AppendHostEvent


class InputSourceOverflowError(RuntimeError):
    """The pending run reached the receiver's fixed batch bound."""


class InputSourceOnBlender:
    """One Blender contact, delivering into one engine receiver.

    Create it when the pointer goes down and let it go when the stroke ends. It holds the receiver
    and the engine by reference; both must outlive it.
    """

    def __init__(self, engine: object, receiverId: int, contactId: int, maximumBatchSamples: int) -> None:
        if maximumBatchSamples <= 0:
            raise ValueError("a Blender input source needs a positive batch bound")
        self._engine = engine
        self._receiverId = receiverId
        self._contactId = contactId
        self._maximumBatchSamples = maximumBatchSamples
        self._batch = engine.Receivers.Batch(maximumBatchSamples)
        self._ordinal = 0
        self._sequence = 0
        self._open = False
        self._snapshot: ReceiverSnapshot | None = None

    @property
    def Sequence(self) -> int:
        """How many events this contact has collected. The next one takes the number after."""
        return self._sequence

    @property
    def Unsent(self) -> int:
        """Events collected but not yet accepted by the receiver."""
        return len(self._batch)

    @property
    def Snapshot(self) -> ReceiverSnapshot | None:
        """What the receiver last accepted, or None before it has accepted anything."""
        return self._snapshot

    def Begin(self) -> None:
        """Open the contact. Every later call belongs to it until it is finished or cancelled."""
        self._engine.Receivers.BeginContact(self._receiverId, self._contactId)
        self._open = True

    def NextSequence(self) -> int:
        """Take the ordinal the next collected event carries."""
        self._sequence += 1
        return self._sequence

    def Collect(self, event: Mapping[str, object]) -> None:
        """Hold one translated event without calling the engine."""
        if len(self._batch) >= self._maximumBatchSamples:
            raise InputSourceOverflowError(f"a Blender input run holds at most {self._maximumBatchSamples} samples")
        AppendHostEvent(self._batch, event)

    def CollectAll(self, events: Iterable[Mapping[str, object]]) -> None:
        """Hold several translated events without calling the engine."""
        for event in events:
            self.Collect(event)

    def Submit(self) -> bool:
        """Send everything collected since the last submission.

        Returns False and keeps the run in hand when the engine's lane is already executing. That is
        contention rather than failure: the lane refuses instead of blocking so a real-time input
        thread never stalls, and the events go out with the next run rather than being dropped.
        """
        if not len(self._batch):
            return True
        try:
            snapshot = self._engine.Receivers.Submit(self._receiverId, self._contactId, self._ordinal + 1, self._batch)
        except EngineError as error:
            if error.Status != FD_RECEIVER_STATUS_BUSY:
                raise
            return False
        self._ordinal += 1
        self._batch.Clear()
        self._snapshot = snapshot
        return True

    def Finish(self) -> int:
        """Send whatever is left and close the contact. Returns the events never accepted."""
        return self._close(FD_RECEIVER_CONTACT_FINISHED, flush=True)

    def Cancel(self) -> int:
        """Abandon the contact. Nothing already committed is taken back; only unsent input is lost."""
        return self._close(FD_RECEIVER_CONTACT_CANCELLED, flush=False)

    def _close(self, contactEnd: int, *, flush: bool) -> int:
        """End the contact exactly once, whichever way the stroke stopped."""
        if not self._open:
            return 0
        if flush:
            # Whatever arrived after the last measured position is still real input, so it goes too.
            self.Submit()
        dropped = len(self._batch)
        self._batch.Clear()
        self._open = False
        self._engine.Receivers.EndContact(self._receiverId, self._contactId, contactEnd)
        return dropped
