"""flexible_drawing_raster_brush.h in Python. Generated: do not edit — see this package's __init__.

The raster_brush interface: its table, its records, its constants, and its host values.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from .bootstrap import fd_engine, fd_engine_status

from .receiver import fd_receiver_desc, fd_receiver_snapshot


# Limits
# Bounds the engine enforces on host-supplied sizes before they reach an allocator.
FD_RASTER_BRUSH_MAX_PACKET_DABS = 1048576


# Interfaces
# Names and generations for fd_engine_get_interface.
FD_INTERFACE_RASTER_BRUSH = "raster_brush"
FD_INTERFACE_RASTER_BRUSH_VERSION = 1


class fd_raster_brush_desc(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("maximum_packet_dabs", ctypes.c_uint64),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


class fd_raster_brush_api(ctypes.Structure):
    """Engine-owned table; struct_size reports how many entry points it populated."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        (
            "create_receiver",
            ctypes.CFUNCTYPE(
                fd_engine_status, fd_engine, ctypes.POINTER(fd_receiver_desc), ctypes.POINTER(fd_raster_brush_desc),
                ctypes.POINTER(fd_receiver_snapshot)
            ),
        ),
    ]


@dataclass(frozen=True)
class RasterBrushDesc:
    """Host-side value of one `fd_raster_brush_desc`, detached from the engine's memory."""

    #: Largest dab packet this receiver may produce after continuous placement. Note: Must be nonzero and no greater
    #: than Note: Independent of
    MaximumPacketDabs: int

    @classmethod
    def FromRecord(cls, record: fd_raster_brush_desc) -> "RasterBrushDesc":
        """Copy an engine-filled record into an immutable host value."""
        return cls(int(record.maximum_packet_dabs))

    def ToRecord(self) -> fd_raster_brush_desc:
        """Marshal this value into a fresh `fd_raster_brush_desc`, sized and ready to hand across."""
        return fd_raster_brush_desc(int(self.MaximumPacketDabs))
