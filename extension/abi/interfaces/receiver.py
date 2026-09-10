"""The painting receiver interface, mirroring flexible_drawing_receiver.h.

Wraps `fd_receiver_api`. A receiver is one painting session: a host opens one, opens a contact on
it, submits runs of samples, and closes the contact when the pen lifts. Every call names the
receiver it is for, so nothing about it is implicit.

One call carries a whole batch of samples on purpose. Each call into the native library costs time,
so we make few large calls instead of many small ones. Never add a method that sends one sample at
a time.

A host fills an `InputBatch`, which is the buffer the engine reads. Nothing is copied between the
two: the samples are written once, where the engine will look for them.
"""

from __future__ import annotations

import array
import ctypes

from ..errors import EngineError
from ..generated import (
    FD_INTERFACE_RECEIVER,
    FD_INTERFACE_RECEIVER_VERSION,
    FD_RECEIVER_CONTACT_FINISHED,
    FD_RECEIVER_MAX_SAMPLES,
    FD_RECEIVER_ORIGIN_MEASURED,
    ReceiverSnapshot,
    fd_input_batch,
    fd_receiver_api,
    fd_receiver_desc,
    fd_receiver_snapshot,
)
from . import Interface

# Growth policy for the reused sample buffer: doubling keeps reallocation off the stroke path.
_MINIMUM_CAPACITY = 64


#: Every field the engine reads: the name used here, the array item type, how many numbers make one
#: sample, the C record's name, and the value the engine uses when the array is absent.
#:
#: Position is two numbers in one array because x and y are always both there, so pairing them costs
#: nothing and lets the engine load a position in one instruction. Everything else is on its own,
#: because each is independently optional and pairing would force a host to supply both or neither.
_FIELDS = (
    ("xy", "d", 2, "xy", 0.0),
    ("pressure", "d", 1, "pressure", 1.0),
    ("timeNanoseconds", "Q", 1, "time_nanoseconds", 0),
    ("sequence", "Q", 1, "sequence", 0),
    ("origin", "B", 1, "origin", FD_RECEIVER_ORIGIN_MEASURED),
)
_FIELD_NAMES = frozenset(name for name, _, _, _, _ in _FIELDS)
#: The pointer type each field has on the C record, taken from the generated declaration.
_POINTER_TYPES = dict(fd_input_batch._fields_)


def _address(buffer: object) -> ctypes.c_void_p:
    """The address of a buffer's first byte. Nothing is copied."""
    return ctypes.c_void_p(ctypes.addressof(ctypes.c_char.from_buffer(buffer)))


class InputBatch:
    """A run of input samples, in the memory the engine will read.

    The engine reads one array per field — position, pressure, timing — each with its own stride, so
    a host hands over its own memory in whatever shape it already keeps it. This class is the simple
    way to build that memory: `Append` writes each field into its array in place, so a sample is
    written once and nothing is copied on the way across.

    ```python
    batch = engine.Receivers.Batch()
    for event in events:
        batch.Append(x=event.x, y=event.y, pressure=event.pressure)
    result = engine.Receivers.Submit(receiverId, contactId, ordinal, batch)
    ```

    Only `x` and `y` have to be given, and they travel together as one pair. Anything left out takes
    the default the C header documents — full pressure, measured input, the sample's position in the
    batch as its ordinal — and no array is allocated for it at all. A mouse has no pressure, so it
    simply never mentions pressure.

    Keep one batch and reuse it. `Clear` empties it without giving the memory back, so a stroke that
    submits every frame allocates once and then never again.

    When the numbers already exist somewhere — an attribute array read out of Blender, a buffer
    shared with the GPU — use `Borrowing` instead. That points the engine at them and copies nothing.

    The arguments are keyword-only on purpose. Six numbers in a row is exactly where a position and
    a pressure end up in each other's places, and that mistake is silent.
    """

    def __init__(self, capacity: int = _MINIMUM_CAPACITY) -> None:
        self._count = 0
        # A position is always needed, so it is sized up front and then reused. The rest appear only
        # if a sample gives them a value.
        self._arrays: dict[str, array.array] = {"xy": array.array("d", [0.0]) * (max(capacity, 1) * 2)}
        self._borrowed: dict[str, tuple[object, int]] | None = None

    def __len__(self) -> int:
        return self._count

    @classmethod
    def Borrowing(cls, count: int, **arrays: object) -> InputBatch:
        """Point at numbers that already exist, without copying them.

        Pass `xy`, and any of `pressure`, `timeNanoseconds`, `sequence` and `origin`. Each is
        anything supporting the buffer protocol — an `array.array`, a `memoryview`, a numpy array.
        `xy` holds two numbers per sample, x then y; the rest hold one. The stride comes from the
        buffer's item size, so each buffer holds one field rather than whole samples interleaved. A
        host with interleaved records calls the C interface directly, where every stride is given.

        The buffers are read during `Submit` and not kept, but they must stay alive and unchanged
        until it returns.
        """
        borrowing = cls(capacity=1)
        borrowing._arrays = {}
        borrowing._count = count
        borrowing._borrowed = {}
        for name, buffer in arrays.items():
            if name not in _FIELD_NAMES:
                raise EngineError(None, f"a stroke batch has no '{name}' field; it has {sorted(_FIELD_NAMES)}")
            components = next(width for field, _, width, _, _ in _FIELDS if field == name)
            view = memoryview(buffer)
            if len(view) < count * components:
                raise EngineError(
                    None,
                    f"the '{name}' buffer holds {len(view)} numbers, not the {count * components} "
                    f"that {count} samples need",
                )
            borrowing._borrowed[name] = (buffer, view.itemsize * components)
        if "xy" not in borrowing._borrowed:
            raise EngineError(None, "a stroke batch needs xy; a sample without a position is not one")
        return borrowing

    def Clear(self) -> None:
        """Forget the samples, keeping the memory for the next run."""
        self._count = 0

    def Append(
        self,
        *,
        x: float,
        y: float,
        pressure: float | None = None,
        timeNanoseconds: int | None = None,
        sequence: int | None = None,
        origin: int | None = None,
    ) -> None:
        """Add one sample. Anything left out keeps the engine's default and costs no memory."""
        if self._borrowed is not None:
            raise EngineError(None, "a borrowing batch points at someone else's numbers and cannot be appended to")
        if self._count >= FD_RECEIVER_MAX_SAMPLES:
            raise EngineError(None, f"a stroke batch holds at most {FD_RECEIVER_MAX_SAMPLES} samples")
        given = ((x, y), pressure, timeNanoseconds, sequence, origin)
        for value, (name, itemType, components, _, default) in zip(given, _FIELDS, strict=True):
            if value is None and name not in self._arrays:
                continue
            values = self._arrays.get(name)
            if values is None:
                # A field first given part-way through: fill the samples already here with the
                # default, so every array stays as long as the batch.
                values = (
                    array.array(itemType, [default]) * (self._count * components)
                    if self._count
                    else array.array(itemType)
                )
                self._arrays[name] = values
            settled = (default,) * components if value is None else (value if components > 1 else (value,))
            start = self._count * components
            for offset, number in enumerate(settled):
                if start + offset < len(values):
                    # Reusing memory a previous run already grew, which is why Clear keeps it.
                    values[start + offset] = number
                else:
                    values.append(number)
        self._count += 1

    def _describe(self) -> fd_input_batch:
        """The pointers and strides the engine reads. Valid while this batch is unchanged."""
        described = fd_input_batch(self._count)
        held = self._borrowed if self._borrowed is not None else self._arrays
        for name, _, components, record, _ in _FIELDS:
            buffer = held.get(name)
            if buffer is None:
                continue
            source, stride = buffer if self._borrowed is not None else (buffer, buffer.itemsize * components)
            setattr(described, record, ctypes.cast(_address(source), _POINTER_TYPES[record]))
            setattr(described, f"{record}_stride", stride)
        return described


class ReceiverInterface(Interface):
    """Open painting receivers and submit runs of input samples to them."""

    NAME = FD_INTERFACE_RECEIVER
    VERSION = FD_INTERFACE_RECEIVER_VERSION
    TABLE = fd_receiver_api
    ATTRIBUTE = "Receivers"

    def Batch(self, capacity: int = _MINIMUM_CAPACITY) -> InputBatch:
        """A new batch to fill. Keep it and reuse it rather than making one per stroke."""
        return InputBatch(capacity)

    def Create(
        self,
        *,
        seed: int,
        tileExtent: int = 64,
        maximumBatchSamples: int = 1024,
        inputCapabilities: int = 0,
    ) -> ReceiverSnapshot:
        """Open a painting receiver and return its identity and starting revision.

        `seed` is the replay seed for deterministic brush variation: the same samples and seed always
        produce the same committed result within one engine version. It belongs to the receiver
        rather than to a submission, because varying it part-way through would change work the
        receiver has already done.

        `tileExtent` is how finely the receiver reports what changed, in canvas units, not a picture
        size. `maximumBatchSamples` is the largest run it will accept; it reserves that much once, so
        a host that submits every frame never reaches an allocator afterwards.

        `inputCapabilities` is a bitwise OR of the FD_RECEIVER_INPUT_* values the host's own source
        really produces. Claiming one the device lacks admits a tool that then behaves wrongly, which
        is worse than the tool being unavailable.
        """
        desc = fd_receiver_desc(seed, tileExtent, maximumBatchSamples, inputCapabilities)
        record = fd_receiver_snapshot()
        self._invoke(self._entry("create"), ctypes.byref(desc), ctypes.byref(record))
        return ReceiverSnapshot.FromRecord(record)

    def BeginContact(self, receiverId: int, contactId: int) -> None:
        """Open a contact on a receiver, which carries one at a time.

        `contactId` is the host's own nonzero identity for this stroke. Every submission repeats it,
        so a run left over from a contact that has ended is refused rather than appended to the next
        one.
        """
        self._invoke(self._entry("begin_contact"), receiverId, contactId)

    def Submit(self, receiverId: int, contactId: int, batchOrdinal: int, batch: InputBatch) -> ReceiverSnapshot:
        """Extend an open contact with one run of samples, and report what the receiver accepted.

        `batchOrdinal` increases strictly from one within a contact. It is what lets the engine refuse
        a run that arrived late rather than applying it out of order.

        Committed samples are final; predicted ones are provisional and are replaced whole by the next
        submission, so a host draws them but must not treat them as finished.

        The batch is read during the call and not kept, so it can be cleared and refilled as soon as
        this returns.

        Raises EngineError with FD_RECEIVER_STATUS_BUSY when a submission is already running on this
        engine. That is contention, not failure: the lane refuses rather than blocking so a real-time
        input thread never stalls, and the caller may retry on its next frame.
        """
        if not len(batch):
            raise EngineError(None, "an input batch must carry at least one sample")
        described = batch._describe()
        record = fd_receiver_snapshot()
        self._invoke(
            self._entry("submit"),
            receiverId,
            contactId,
            batchOrdinal,
            ctypes.byref(described),
            ctypes.byref(record),
        )
        return ReceiverSnapshot.FromRecord(record)

    def EndContact(self, receiverId: int, contactId: int, contactEnd: int = FD_RECEIVER_CONTACT_FINISHED) -> None:
        """Close the open contact, keeping committed work and dropping everything provisional."""
        self._invoke(self._entry("end_contact"), receiverId, contactId, contactEnd)

    def Close(self, receiverId: int) -> None:
        """Close a receiver and release everything it owns. Any open contact is cancelled first."""
        self._invoke(self._entry("close"), receiverId)
