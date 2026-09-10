"""The iceoryx2 ports a host uses to reach the Realtime Plane.

Three ports: requests out on the control service, and two subscriptions in, tool state and tile
results. The service settings must equal the Realtime Plane's, which reads them from the same
profile, or iceoryx2 refuses to open the service.

Nothing here waits. A request returns at once with a reply to poll, and a subscription returns
None when nothing has arrived. A received message is copied out of shared memory before it is
returned, so the sample goes back to the Realtime Plane immediately.
"""

from __future__ import annotations

import ctypes

from .process import Endpoints
from .profile import Profile

# One host and one Realtime Plane share each service.
_NODES = 2


def _iceoryx2() -> object:
    # Imported here, not at module load: Blender installs the bundled wheel only when the extension
    # is enabled, and the rest of the package must import without it.
    import iceoryx2

    return iceoryx2


def _copied(sample: object) -> bytes:
    return ctypes.string_at(sample.payload_ptr, sample.payload().len())


class Reply:
    """The answer to one request, which arrives later."""

    def __init__(self, pending: object) -> None:
        self._pending = pending

    def Take(self) -> bytes | None:
        """The answer, once it has arrived; None until then."""
        response = self._pending.receive()
        return None if response is None else _copied(response)


class Iceoryx2Channels:
    """The host end of the control, tool-state and tile-result services."""

    def __init__(self, endpoints: Endpoints) -> None:
        iox2 = _iceoryx2()
        settings = Profile.SETTINGS
        self._node = iox2.NodeBuilder.new().create(iox2.ServiceType.Ipc)
        control = (
            self._node.service_builder(iox2.ServiceName.new(endpoints.Control))
            .request_response(iox2.Slice[ctypes.c_uint8], iox2.Slice[ctypes.c_uint8])
            .enable_safe_overflow_for_requests(False)
            .enable_safe_overflow_for_responses(False)
            .max_active_requests_per_client(settings.Actions.WindowRecords)
            .max_response_buffer_size(settings.Actions.WindowRecords)
            .max_servers(1)
            .max_clients(1)
            .max_nodes(_NODES)
            .open_or_create()
        )
        self._client = control.client_builder().initial_max_slice_len(settings.ControlFrameBytes).create()
        self._states = self._subscriber(endpoints.State, settings.ToolStates.WindowRecords)
        self._results = self._subscriber(endpoints.Results, settings.TileResults.WindowRecords)

    def _subscriber(self, name: str, window: int) -> object:
        iox2 = _iceoryx2()
        service = (
            self._node.service_builder(iox2.ServiceName.new(name))
            .publish_subscribe(iox2.Slice[ctypes.c_uint8])
            .enable_safe_overflow(False)
            .subscriber_max_buffer_size(window)
            .max_publishers(1)
            .max_subscribers(1)
            .max_nodes(_NODES)
            .open_or_create()
        )
        return service.subscriber_builder().buffer_size(window).create()

    def Send(self, frames: bytes) -> Reply:
        """Send one request made of `frames`; its answer arrives later."""
        request = self._client.loan_slice_uninit(len(frames))
        ctypes.memmove(request.payload_ptr, frames, len(frames))
        return Reply(request.assume_init().send())

    def ReceiveState(self) -> bytes | None:
        """The next tool-state record, or None."""
        sample = self._states.receive()
        return None if sample is None else _copied(sample)

    def ReceiveResult(self) -> bytes | None:
        """The next tile-results message, record and region together, or None."""
        sample = self._results.receive()
        return None if sample is None else _copied(sample)
