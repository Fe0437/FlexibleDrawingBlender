"""A host's session with the Realtime Plane: actions out, tool state and canvas results in.

The host never waits on the Realtime Plane. `Advance` does whatever can be done now and returns:
it collects the answer to the one request under way, reads every record that has arrived, and
sends the next request, which carries the acknowledgements and region releases the reads earned
and the actions the host asked for since. A host calls it from a timer.

Two values exist for every setting a person changes. The *pending* value is what the host asked
for and the Realtime Plane has not applied yet; the *effective* value is what the Realtime Plane
reports in effect. They differ for as long as the request travels, and for longer while a stroke is
being painted, because a stroke keeps the tool it started with. A host shows both.

Asking again before a request was sent replaces it: a slider dragged across its range sends the
value it ended on, not every value it passed.

A session ends, and stays ended, when the Realtime Plane closes it, when it breaks the protocol, or
when it stops answering. Records of any other session are dropped unread: they belong to a session
the Realtime Plane already replaced. Whoever owns the session opens a new one with a new identity.

```python
session = RealtimePlaneSession(Iceoryx2Channels(endpoints), sessionId)
session.Request("presentation.tool_ui", "pressure_brush.set_hardness", 0.8)
while session.Pending("presentation.tool_ui", "pressure_brush.set_hardness") is not None:
    session.Advance()
session.Effective("presentation.tool_ui", "pressure_brush.hardness")  # 0.8
```
"""

from __future__ import annotations

from collections.abc import Callable
import enum
import struct
import time

from .profile import Frames, Profile

#: A value or an identity, such as a tool, a person picked.
ActionValue = float | tuple[float, ...] | str

_ACKNOWLEDGEMENT_BODY = struct.Struct("<HQ")
# An open request can be lost: sent before the Realtime Plane created its server, it reaches nobody.
# So an unanswered open is given up quickly and tried again. Once a session is open, nothing is lost,
# and a late answer means a busy Realtime Plane, such as one preparing a newly selected tool.
_DEFAULT_OPEN_SECONDS = 1.0
_DEFAULT_REPLY_SECONDS = 5.0
_CLOSE_WAIT_SECONDS = 0.2
_CLOSE_POLL_SECONDS = 0.005


class SessionState(enum.Enum):
    """Where a session is in its life."""

    OPENING = "opening"  #: asked for; the Realtime Plane has not answered yet
    OPEN = "open"  #: accepted; records flow both ways
    CLOSED = "closed"  #: over for good; see `CloseReason`


class RealtimePlaneSession:
    """One session over channels the caller opened. It never blocks except in `Close`."""

    def __init__(
        self,
        channels: object,
        session: int,
        *,
        openSeconds: float = _DEFAULT_OPEN_SECONDS,
        replySeconds: float = _DEFAULT_REPLY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < session < 1 << 64:
            raise ValueError("a session identity is a nonzero 64-bit number")
        self.Id = session
        self.State = SessionState.OPENING
        self.CloseReason = ""
        self.ToolRevision = 0
        """The revision of the latest tool state; actions are sent against it."""
        self.Mirror = Profile.CanvasMirror()
        """The host's copy of the canvas, from tile results."""
        self.ChangedTiles: set[tuple[int, int]] = set()
        """Tiles the mirror changed since the host last cleared this set."""
        self.StaleRecords = 0
        """Records of a replaced session that arrived and were dropped."""
        self._channels = channels
        self._openSeconds = openSeconds
        self._replySeconds = replySeconds
        self._clock = clock
        self._effective: dict[tuple[str, str], ActionValue] = {}
        self._queued: dict[tuple[str, str], ActionValue] = {}
        self._sent: dict[tuple[str, str], tuple[int, ActionValue]] = {}
        self._actionSequence = 0
        self._stateSequence = self._stateAcknowledged = 0
        self._resultSequence = self._resultAcknowledged = 0
        self._releases: list[int] = []
        self._requestThrough = 0  # the last action the request under way carries, or 0
        settings = Profile.SETTINGS
        self._send(
            Frames.EncodeSessionOpen(
                session,
                (settings.ToolStateCapability, settings.TileResultsCapability),
                (settings.ToolStateCapability,),
            )
        )

    # What the host reads.

    def Effective(self, owner: str, state: str) -> ActionValue | None:
        """The value the Realtime Plane reports in effect for one state binding, if it reported one."""
        return self._effective.get((owner, state))

    def Pending(self, owner: str, action: str) -> ActionValue | None:
        """The value requested through one action binding that has not taken effect yet."""
        key = (owner, action)
        if key in self._queued:
            return self._queued[key]
        sent = self._sent.get(key)
        return None if sent is None else sent[1]

    # What the host does.

    def Request(self, owner: str, action: str, value: ActionValue) -> bool:
        """Ask for an action; it is sent on the next `Advance`. False when the value has no payload."""
        if self.State is SessionState.CLOSED:
            return False
        try:
            _payload(owner, action, value)  # refused now, rather than when it is sent
        except (Profile.PayloadError, TypeError):
            return False
        self._queued[(owner, action)] = value
        return True

    def Advance(self) -> bool:
        """Do what can be done now, never waiting. Returns whether anything a host shows changed."""
        if self.State is SessionState.CLOSED:
            return False
        changed = self._collectReply()
        if self.State is SessionState.OPEN:
            changed = self._readStates() or changed
            changed = self._readResults() or changed
        if self.State is SessionState.OPEN and self._reply is None:
            self._sendNext()
        return changed

    def Close(self) -> None:
        """End the session, waiting briefly for the Realtime Plane to hear it. Safe to repeat."""
        if self.State is SessionState.CLOSED:
            return
        reply = self._channels.Send(Frames.EncodeSessionClose(self.Id))
        deadline = self._clock() + _CLOSE_WAIT_SECONDS
        while reply.Take() is None and self._clock() < deadline:
            time.sleep(_CLOSE_POLL_SECONDS)
        self._end("closed by the host")

    # The exchange.

    def _send(self, frames: bytes) -> None:
        self._reply = self._channels.Send(frames)
        self._sentAt = self._clock()

    def _end(self, reason: str) -> None:
        self.State = SessionState.CLOSED
        self.CloseReason = reason
        self._reply = None
        self._queued.clear()
        self._sent.clear()

    def _collectReply(self) -> bool:
        if self._reply is None:
            return False
        answer = self._reply.Take()
        if answer is None:
            patience = self._openSeconds if self.State is SessionState.OPENING else self._replySeconds
            if self._clock() - self._sentAt > patience:
                self._end("the Realtime Plane stopped answering")
                return True
            return False
        self._reply = None
        expected, self._requestThrough = self._requestThrough, 0
        acknowledged = 0
        for kind, session, body in Frames.SplitFrames(answer):
            if session != self.Id:
                continue  # about a session the Realtime Plane replaced
            if kind == Frames.SESSION_ACCEPT:
                self.State = SessionState.OPEN
            elif kind == Frames.SESSION_REJECT:
                self._end("the Realtime Plane refused the session")
            elif kind == Frames.SESSION_CLOSE:
                self._end(f"the Realtime Plane closed the session (reason {body[0] if body else 0})")
            elif kind == Frames.ACKNOWLEDGEMENT:
                stream, through = _ACKNOWLEDGEMENT_BODY.unpack(body)
                if stream == Profile.SETTINGS.Actions.Stream:
                    acknowledged = max(acknowledged, through)
        if self.State is SessionState.OPEN and acknowledged < expected:
            self._end("the Realtime Plane did not accept an action")
        return True

    def _readStates(self) -> bool:
        changed = False
        while (message := self._channels.ReceiveState()) is not None:
            record = Frames.DecodeRecord(memoryview(message))
            if record.Session != self.Id:
                self.StaleRecords += 1
                continue
            if record.Sequence != self._stateSequence + 1:
                self._end(f"tool state {record.Sequence} arrived after {self._stateSequence}")
                return True
            self._stateSequence = record.Sequence
            snapshot = Profile.DecodeToolState(record.Payload)
            self.ToolRevision = record.Revision
            self._effective = {(entry.Owner, entry.State): entry.Identity for entry in snapshot.Identities}
            self._effective.update({(entry.Owner, entry.State): entry.Value for entry in snapshot.Values})
            applied = snapshot.AppliedActionSequence
            self._sent = {key: sent for key, sent in self._sent.items() if sent[0] > applied}
            changed = True
        return changed

    def _readResults(self) -> bool:
        changed = False
        while (message := self._channels.ReceiveResult()) is not None:
            view = memoryview(message)
            record = Frames.DecodeRegionRecord(view)
            if record.Session != self.Id:
                self.StaleRecords += 1
                continue
            if record.Sequence != self._resultSequence + 1:
                self._end(f"tile results {record.Sequence} arrived after {self._resultSequence}")
                return True
            end = record.Offset + record.Length
            if record.PayloadType != Profile.SETTINGS.TileResultsRegion or end > len(view):
                self._end("a tile-results region does not lie inside its message")
                return True
            self._resultSequence = record.Sequence
            results = Profile.DecodeTileResults(view[record.Offset : end])
            self.Mirror.Apply(results, record.Revision)
            self.ChangedTiles.update((tile.X, tile.Y) for tile in results.Tiles)
            self._releases.append(record.Region)
            changed = True
        return changed

    def _sendNext(self) -> None:
        """Send what reading earned and what the host asked for, as one request, if there is any."""
        settings = Profile.SETTINGS
        frames = bytearray()
        if self._stateSequence > self._stateAcknowledged:
            frames += Frames.EncodeAcknowledgement(self.Id, settings.ToolStates.Stream, self._stateSequence)
            self._stateAcknowledged = self._stateSequence
        if self._resultSequence > self._resultAcknowledged:
            frames += Frames.EncodeAcknowledgement(self.Id, settings.TileResults.Stream, self._resultSequence)
            self._resultAcknowledged = self._resultSequence
        for region in self._releases:
            frames += Frames.EncodeRegionRelease(self.Id, region)
        self._releases.clear()
        first = self._actionSequence + 1
        for (owner, action), value in list(self._queued.items()):
            payloadType, payload = _payload(owner, action, value)
            sequence = self._actionSequence + 1
            record = Frames.EncodeRecord(
                self.Id, settings.Actions.Stream, sequence, self.ToolRevision, payloadType, payload
            )
            full = sequence - first == settings.Actions.WindowRecords
            if full or len(frames) + len(record) > settings.ControlFrameBytes:
                break  # the rest go with the next request
            frames += record
            self._actionSequence = sequence
            self._sent[(owner, action)] = (sequence, value)
            del self._queued[(owner, action)]
        if frames:
            self._send(bytes(frames))
            self._requestThrough = self._actionSequence if self._actionSequence >= first else 0


def _payload(owner: str, action: str, value: ActionValue) -> tuple[int, bytes]:
    """The payload type and bytes of one action: an identity for text, a value otherwise."""
    settings = Profile.SETTINGS
    if isinstance(value, str):
        identity = Profile.IdentityAction(owner, action, value)
        return settings.IdentityActionPayload, Profile.EncodeIdentityAction(identity)
    if not isinstance(value, (float, tuple)):
        raise TypeError(f"no action payload carries a {type(value).__name__}")
    return settings.ValueActionPayload, Profile.EncodeValueAction(Profile.ValueAction(owner, action, value))
