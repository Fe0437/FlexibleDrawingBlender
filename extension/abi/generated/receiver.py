"""flexible_drawing_receiver.h in Python. Generated: do not edit — see this package's __init__.

The receiver interface: its table, its records, its constants, and its host values.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from .bootstrap import fd_engine, fd_engine_status


# Status codes
# Zero is success. The bootstrap owns 0-999; each interface owns a block from 1000 up.
FD_RECEIVER_STATUS_BUSY = 1100
FD_RECEIVER_STATUS_LIMIT = 1104
FD_RECEIVER_STATUS_NO_CONTACT = 1102
FD_RECEIVER_STATUS_OUT_OF_ORDER = 1103
FD_RECEIVER_STATUS_REJECTED = 1105
FD_RECEIVER_STATUS_UNKNOWN = 1101


# Limits
# Bounds the engine enforces on host-supplied sizes before they reach an allocator.
FD_RECEIVER_MAX_COUNT = 64
FD_RECEIVER_MAX_SAMPLES = 1048576


# Interfaces
# Names and generations for fd_engine_get_interface.
FD_INTERFACE_RECEIVER = "receiver"
FD_INTERFACE_RECEIVER_VERSION = 1


# Constants
# Every other value the header pins, which a host compares against by number.
FD_RECEIVER_CONTACT_CANCELLED = 1
FD_RECEIVER_CONTACT_FINISHED = 0
FD_RECEIVER_INPUT_COALESCING = 2
FD_RECEIVER_INPUT_CORRECTION = 8
FD_RECEIVER_INPUT_ERASER = 128
FD_RECEIVER_INPUT_HOVER = 256
FD_RECEIVER_INPUT_PREDICTION = 4
FD_RECEIVER_INPUT_PRESSURE = 1
FD_RECEIVER_INPUT_TILT = 32
FD_RECEIVER_INPUT_TIMESTAMP = 16
FD_RECEIVER_INPUT_TWIST = 64
FD_RECEIVER_ORIGIN_COALESCED = 1
FD_RECEIVER_ORIGIN_CORRECTED = 3
FD_RECEIVER_ORIGIN_MEASURED = 0
FD_RECEIVER_ORIGIN_PREDICTED = 2


class fd_input_batch(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("sample_count", ctypes.c_uint64),
        ("xy", ctypes.POINTER(ctypes.c_double)),
        ("xy_stride", ctypes.c_uint64),
        ("pressure", ctypes.POINTER(ctypes.c_double)),
        ("pressure_stride", ctypes.c_uint64),
        ("time_nanoseconds", ctypes.POINTER(ctypes.c_uint64)),
        ("time_nanoseconds_stride", ctypes.c_uint64),
        ("sequence", ctypes.POINTER(ctypes.c_uint64)),
        ("sequence_stride", ctypes.c_uint64),
        ("origin", ctypes.POINTER(ctypes.c_uint8)),
        ("origin_stride", ctypes.c_uint64),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


class fd_input_sample(ctypes.Structure):
    """Array-element record: frozen layout, because callers stride by their own sizeof."""

    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("pressure", ctypes.c_double),
        ("time_nanoseconds", ctypes.c_uint64),
        ("sequence", ctypes.c_uint64),
        ("origin", ctypes.c_uint8),
    ]


class fd_receiver_desc(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("seed", ctypes.c_uint64),
        ("tile_extent", ctypes.c_uint32),
        ("maximum_batch_samples", ctypes.c_uint32),
        ("input_capabilities", ctypes.c_uint32),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


class fd_receiver_snapshot(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("receiver_id", ctypes.c_uint64),
        ("revision", ctypes.c_uint64),
        ("committed_sequence", ctypes.c_uint64),
        ("accepted_sample_count", ctypes.c_uint64),
        ("predicted_sample_count", ctypes.c_uint64),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


class fd_receiver_api(ctypes.Structure):
    """Engine-owned table; struct_size reports how many entry points it populated."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        (
            "create",
            ctypes.CFUNCTYPE(
                fd_engine_status, fd_engine, ctypes.POINTER(fd_receiver_desc), ctypes.POINTER(fd_receiver_snapshot)
            ),
        ),
        ("begin_contact", ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.c_uint64, ctypes.c_uint64)),
        (
            "submit",
            ctypes.CFUNCTYPE(
                fd_engine_status, fd_engine, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
                ctypes.POINTER(fd_input_batch), ctypes.POINTER(fd_receiver_snapshot)
            ),
        ),
        (
            "end_contact",
            ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32),
        ),
        ("close", ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.c_uint64)),
    ]


@dataclass(frozen=True)
class InputSample:
    """Host-side value of one `fd_input_sample`, detached from the engine's memory."""

    #: Horizontal position in the drawing, in canvas units, increasing right.
    X: float
    #: Vertical position in the drawing, in canvas units, increasing down.
    Y: float
    #: Normalized pen force in [0, 1]. Devices without pressure should report 1.0.
    Pressure: float
    #: When the host observed the sample, in nanoseconds. Note: Any monotonic clock; the engine reads only
    #: differences, never the absolute value. It must not go backwards within one submission.
    TimeNanoseconds: int
    #: Host-assigned ordinal, increasing strictly across a contact. Note: This, not array order, defines the
    #: contact's order. Gaps are permitted and mean samples were dropped; a repeat or a decrease is rejected.
    #: Committed sequences must also beat everything already committed; a predicted sequence need not, because the
    #: next submission replaces every prediction anyway.
    Sequence: int
    #: One of the FD_RECEIVER_ORIGIN_* values; any other value is rejected.
    Origin: int

    @classmethod
    def FromRecord(cls, record: fd_input_sample) -> "InputSample":
        """Copy an engine-filled record into an immutable host value."""
        return cls(
            float(record.x), float(record.y), float(record.pressure), int(record.time_nanoseconds),
            int(record.sequence), int(record.origin)
        )

    def ToRecord(self) -> fd_input_sample:
        """Marshal this value into a fresh `fd_input_sample`, sized and ready to hand across."""
        return fd_input_sample(
            float(self.X), float(self.Y), float(self.Pressure), int(self.TimeNanoseconds), int(self.Sequence),
            int(self.Origin)
        )


@dataclass(frozen=True)
class ReceiverDesc:
    """Host-side value of one `fd_receiver_desc`, detached from the engine's memory."""

    #: Replay seed for deterministic brush variation. Note: The same samples and seed always produce the same
    #: committed result within one engine version. It belongs to the receiver rather than to a submission, because
    #: varying it part-way through would change work already done.
    Seed: int
    #: Width and height of one canvas tile, in canvas units. Must be nonzero. Note: This is how finely the receiver
    #: reports what changed, not a picture size.
    TileExtent: int
    #: Largest submission this receiver will accept, in samples. Note: Clamped to
    MaximumBatchSamples: int
    #: Bitwise OR of the FD_RECEIVER_INPUT_* values the host's source really produces. Note: Zero is valid and means
    #: positions only. It decides which tools this receiver can run, so an untrue claim is worse than an absent
    #: capability.
    InputCapabilities: int

    @classmethod
    def FromRecord(cls, record: fd_receiver_desc) -> "ReceiverDesc":
        """Copy an engine-filled record into an immutable host value."""
        return cls(
            int(record.seed), int(record.tile_extent), int(record.maximum_batch_samples),
            int(record.input_capabilities)
        )

    def ToRecord(self) -> fd_receiver_desc:
        """Marshal this value into a fresh `fd_receiver_desc`, sized and ready to hand across."""
        return fd_receiver_desc(
            int(self.Seed), int(self.TileExtent), int(self.MaximumBatchSamples), int(self.InputCapabilities)
        )


@dataclass(frozen=True)
class ReceiverSnapshot:
    """Host-side value of one `fd_receiver_snapshot`, detached from the engine's memory."""

    #: Identity of the receiver, which every later call on it passes back.
    ReceiverId: int
    #: Version of the work this receiver has accepted, increasing on every change. Note: This, not a tile count, is
    #: what a host stores and compares. A host that has already seen this revision has nothing new to read.
    Revision: int
    #: Highest sample sequence the current contact has committed; zero before any.
    CommittedSequence: int
    #: Samples of the last submission the receiver took; zero when it took none.
    AcceptedSampleCount: int
    #: Provisional samples the receiver is currently holding. Note: Predicted work is replaced whole by the next
    #: submission and dropped when the contact ends, so a host may draw it but must not treat it as final.
    PredictedSampleCount: int

    @classmethod
    def FromRecord(cls, record: fd_receiver_snapshot) -> "ReceiverSnapshot":
        """Copy an engine-filled record into an immutable host value."""
        return cls(
            int(record.receiver_id), int(record.revision), int(record.committed_sequence),
            int(record.accepted_sample_count), int(record.predicted_sample_count)
        )

    def ToRecord(self) -> fd_receiver_snapshot:
        """Marshal this value into a fresh `fd_receiver_snapshot`, sized and ready to hand across."""
        return fd_receiver_snapshot(
            int(self.ReceiverId), int(self.Revision), int(self.CommittedSequence), int(self.AcceptedSampleCount),
            int(self.PredictedSampleCount)
        )
