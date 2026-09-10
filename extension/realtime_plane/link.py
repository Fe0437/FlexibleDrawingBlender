"""A host's link to the Realtime Plane: the process, and a session with it that keeps coming back.

The link is what a host holds. `Open` finds the user's Realtime Plane or starts it; `Advance`,
called from the host's timer, watches the process, keeps a session open, and moves records; `Stop`
ends the process. `Detach` lets go without stopping anything, which is what a host does when it
quits: the Realtime Plane goes on painting and the next host attaches to it.

The link recovers on its own. When the session ends, because the Realtime Plane closed it or
stopped answering, the link opens a new one, with a new identity and new ports, a moment later.
When the process exits, the link says so and waits for `Open`: restarting a program the person
may have closed on purpose is not the link's decision.

An exception from the transport or a malformed record ends the session, never the host: the
Realtime Plane is another program, and nothing it sends may take the host down with it.

```python
link = RealtimePlaneLink(lambda: BundledProgram(directory))
link.Open()
link.Request("presentation.tool_ui", "pressure_brush.set_hardness", 0.8)
bpy.app.timers.register(lambda: (link.Advance(), 1 / 60)[1])  # a host's timer
```
"""

from __future__ import annotations

from collections.abc import Callable
import contextlib
import enum
import logging
import time

from .channels import Iceoryx2Channels
from .process import Attach, Endpoints, EndpointsFor, Program, RealtimePlaneProcess, Scope, Start, StateDirectory
from .session import ActionValue, RealtimePlaneSession, SessionState

_logger = logging.getLogger("flexible_drawing")
#: How long the link waits before opening a session again after one ended.
RECONNECT_SECONDS = 0.5


class LinkState(enum.Enum):
    """What a host can tell a person about the Realtime Plane."""

    STOPPED = "stopped"  #: no Realtime Plane is running for this host
    CONNECTING = "connecting"  #: it runs; a session is being opened
    CONNECTED = "connected"  #: it runs and a session is open


class RealtimePlaneLink:
    """The process and the session, kept together for one host."""

    #: How a host names what its UI acts on through this link.
    Label = "Realtime Plane (external canvas)"

    def __init__(
        self,
        program: Callable[[], Program],
        scope: str | None = None,
        *,
        openChannels: Callable[[Endpoints], object] = Iceoryx2Channels,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.Process: RealtimePlaneProcess | None = None
        self.Session: RealtimePlaneSession | None = None
        self.Message = ""
        """The latest thing that happened that a person may want to know, such as why it stopped."""
        self._program = program
        scope = scope if scope is not None else Scope()
        self._stateDirectory = StateDirectory(scope)
        self._endpoints = EndpointsFor(scope)
        self._openChannels = openChannels
        self._clock = clock
        self._retryAt = 0.0
        self._lastSessionId = 0

    @property
    def State(self) -> LinkState:
        """Where the Realtime Plane is, as a host shows it."""
        if self.Process is None:
            return LinkState.STOPPED
        if self.Session is not None and self.Session.State is SessionState.OPEN:
            return LinkState.CONNECTED
        return LinkState.CONNECTING

    @property
    def Available(self) -> bool:
        """Whether actions can be requested now."""
        return self.State is LinkState.CONNECTED

    @property
    def UnavailableReason(self) -> str:
        """Why actions cannot be requested, as one line a host can show."""
        if self.State is LinkState.STOPPED:
            return f"Open {self.Label} to change these settings"
        return self.Message or f"Connecting to {self.Label}"

    def Reattach(self) -> bool:
        """Attach to the Realtime Plane if one is running; never start one. Returns whether it attached.

        A host calls this when it starts, so a Realtime Plane that outlived the previous host is
        found again without the person asking.
        """
        if self.Process is None or not self.Process.Alive():
            self.Process = Attach(self._stateDirectory)
            if self.Process is not None:
                self._report("attached to the running Realtime Plane")
        return self.Process is not None

    def Open(self) -> None:
        """Attach to the running Realtime Plane, or start one. Raises `OSError` if it cannot start."""
        if not self.Reattach():
            self.Process = Start(self._program(), self._endpoints, self._stateDirectory)
            self._report("started the Realtime Plane")

    def _report(self, message: str) -> None:
        self.Message = message
        self._retryAt = 0.0
        _logger.info("[realtime_plane] %s; pid=%d", message, self.Process.Pid)

    def Advance(self) -> bool:
        """Watch the process, keep a session open and move records. Returns whether anything changed."""
        if self.Process is None:
            return False
        if not self.Process.Alive():
            self._closeSession(None, farewell=False)
            self.Process = None
            self.Message = "the Realtime Plane exited"
            _logger.warning("[realtime_plane] %s", self.Message)
            return True
        if self.Session is None:
            if self._clock() < self._retryAt:
                return False
            return self._connect()
        try:
            changed = self.Session.Advance()
        except Exception as error:  # another program's bytes must never take the host down
            self._closeSession(f"the session failed: {error}")
            return True
        if self.Session.State is SessionState.CLOSED:
            self._closeSession(self.Session.CloseReason)
            return True
        return changed

    def Detach(self) -> None:
        """Close the session and let go; the Realtime Plane keeps running for the next host."""
        self._closeSession(None)
        self.Process = None

    def Stop(self) -> None:
        """Close the session and end the Realtime Plane."""
        process = self.Process
        self.Detach()
        if process is not None:
            process.Stop()
            self.Message = "stopped the Realtime Plane"

    # The session, as a host's UI uses it. Without one, nothing is pending and nothing is known.

    def Request(self, owner: str, action: str, value: ActionValue) -> bool:
        """Ask for an action. False when no session is open or the value has no payload."""
        return self.Session is not None and self.Session.Request(owner, action, value)

    def Pending(self, owner: str, action: str) -> ActionValue | None:
        """The value requested through an action binding that has not taken effect yet."""
        return None if self.Session is None else self.Session.Pending(owner, action)

    def Effective(self, owner: str, state: str) -> ActionValue | None:
        """The value the Realtime Plane reports in effect for a state binding."""
        return None if self.Session is None else self.Session.Effective(owner, state)

    def _connect(self) -> bool:
        # A fresh identity each time, larger than any before it even across host restarts, so the
        # Realtime Plane can always tell a replaced session's late records from the new session's.
        self._lastSessionId = max(time.time_ns(), self._lastSessionId + 1) & ((1 << 63) - 1)
        self.Message = f"connecting to {self.Label}"
        try:
            self.Session = RealtimePlaneSession(
                self._openChannels(self._endpoints), self._lastSessionId, clock=self._clock
            )
        except Exception as error:  # the transport refused; try again later
            self._closeSession(f"could not reach the Realtime Plane: {error}")
        return True

    def _closeSession(self, reason: str | None, farewell: bool = True) -> None:
        """Drop the session, telling the Realtime Plane first unless nobody is left to hear it."""
        session, self.Session = self.Session, None
        if session is not None and farewell:
            # The session is being dropped either way; a Realtime Plane that cannot hear it loses nothing.
            with contextlib.suppress(Exception):
                session.Close()
        if reason is not None:
            self.Message = reason
            self._retryAt = self._clock() + RECONNECT_SECONDS
            _logger.info("[realtime_plane] %s; reconnecting", reason)
