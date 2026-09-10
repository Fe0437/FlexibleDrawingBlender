"""The raster brush interface, mirroring flexible_drawing_raster_brush.h.

Wraps `fd_raster_brush_api`. A receiver is generic: it takes input and reports what changed. How
marks are made is a technique, and the current one places round dabs along the stroke. What that
technique needs bounded — how many dabs one packet may carry — is here rather than on the receiver
record, so a host that paints some other way never sees it.

Opening a receiver through this interface is the same as opening one through the receiver
interface, plus the dab bound. A host that does not ask for this interface gets the engine's
default, which is why the generic path stays usable without knowing what a dab is.
"""

from __future__ import annotations

import ctypes

from ..errors import EngineError
from ..generated import (
    FD_INTERFACE_RASTER_BRUSH,
    FD_INTERFACE_RASTER_BRUSH_VERSION,
    FD_RASTER_BRUSH_MAX_PACKET_DABS,
    ReceiverSnapshot,
    fd_raster_brush_api,
    fd_raster_brush_desc,
    fd_receiver_desc,
    fd_receiver_snapshot,
)
from . import Interface


class RasterBrushInterface(Interface):
    """Opens receivers that paint by placing dabs."""

    NAME = FD_INTERFACE_RASTER_BRUSH
    VERSION = FD_INTERFACE_RASTER_BRUSH_VERSION
    TABLE = fd_raster_brush_api
    ATTRIBUTE = "RasterBrushes"

    def CreateReceiver(
        self,
        *,
        seed: int,
        tileExtent: int = 64,
        maximumBatchSamples: int = 1024,
        inputCapabilities: int = 0,
        maximumPacketDabs: int,
    ) -> ReceiverSnapshot:
        """Open a receiver that places dabs, and report its identity and starting revision."""
        if not 0 < maximumPacketDabs <= FD_RASTER_BRUSH_MAX_PACKET_DABS:
            # Host-side refusal: no call was made, so there is no engine status to carry.
            raise EngineError(None, f"maximumPacketDabs must be 1..{FD_RASTER_BRUSH_MAX_PACKET_DABS}")
        desc = fd_receiver_desc(
            struct_size=ctypes.sizeof(fd_receiver_desc),
            seed=seed,
            tile_extent=tileExtent,
            maximum_batch_samples=maximumBatchSamples,
            input_capabilities=inputCapabilities,
        )
        brush = fd_raster_brush_desc(
            struct_size=ctypes.sizeof(fd_raster_brush_desc),
            maximum_packet_dabs=maximumPacketDabs,
        )
        snapshot = fd_receiver_snapshot(struct_size=ctypes.sizeof(fd_receiver_snapshot))
        self._engine.Check(
            self._create_receiver(self._engine.Handle, ctypes.byref(desc), ctypes.byref(brush), ctypes.byref(snapshot))
        )
        return ReceiverSnapshot.From(snapshot)
