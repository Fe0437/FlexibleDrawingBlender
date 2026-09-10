#!/usr/bin/env python3
"""Check the Realtime Plane session's rules without a transport: what it drops, refuses and sends.

The channels are fakes that answer from a script, so every case is exact: records of a replaced
session are dropped, records out of order or a Realtime Plane that stops answering end the session,
requests respect the actions window, and a request made again before it was sent replaces it. The
same session against a real Realtime Plane is `test_realtime_plane_link.py`.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import types
import unittest

OWNER = "presentation.tool_ui"


class FakeReply:
    def __init__(self, answer: bytes | None) -> None:
        self.answer = answer

    def Take(self) -> bytes | None:
        return self.answer


class FakeChannels:
    """Answers each request with the next scripted reply, and delivers queued records."""

    def __init__(self) -> None:
        self.Sent: list[bytes] = []
        self.Replies: list[bytes | None] = []
        self.States: list[bytes] = []
        self.Results: list[bytes] = []

    def Send(self, frames: bytes) -> FakeReply:
        self.Sent.append(frames)
        return FakeReply(self.Replies.pop(0) if self.Replies else b"")

    def ReceiveState(self) -> bytes | None:
        return self.States.pop(0) if self.States else None

    def ReceiveResult(self) -> bytes | None:
        return self.Results.pop(0) if self.Results else None


class SessionTests(unittest.TestCase):
    client: types.SimpleNamespace

    def setUp(self) -> None:
        self.session = self.client.session
        self.frames = self.client.session.Frames
        self.profile = self.client.session.Profile
        self.now = 0.0
        self.channels = FakeChannels()

    def _accept(self, session: int) -> bytes:
        frames, settings = self.frames, self.profile.SETTINGS
        names = [settings.ToolStateCapability.encode(), settings.TileResultsCapability.encode()]
        body = frames.VERSION.pack(1, 0) + bytes([len(names)]) + b"".join(bytes([len(n)]) + n for n in names)
        return frames.HEADER.pack(frames.MARKER, 1, frames.SESSION_ACCEPT, len(body), session) + body

    def _state(self, session: int, sequence: int, hardness: float, applied: int = 0) -> bytes:
        profile = self.profile
        snapshot = profile.ToolStateSnapshot(
            applied,
            (profile.IdentityState(OWNER, "active_tool", "freehand.pressure_brush"),),
            (profile.ValueState(OWNER, "pressure_brush.hardness", hardness),),
        )
        settings = profile.SETTINGS
        return self.frames.EncodeRecord(
            session,
            settings.ToolStates.Stream,
            sequence,
            sequence,
            settings.ToolStatePayload,
            profile.EncodeToolState(snapshot),
        )

    def _open(self, session: int = 7) -> object:
        self.channels.Replies.append(self._accept(session))
        opened = self.session.RealtimePlaneSession(self.channels, session, replySeconds=1.0, clock=lambda: self.now)
        opened.Advance()
        self.assertIs(opened.State, self.session.SessionState.OPEN)
        return opened

    def test_records_of_a_replaced_session_are_dropped(self) -> None:
        opened = self._open(7)
        self.channels.States += [self._state(6, 1, 0.9), self._state(7, 1, 0.4)]
        self.assertTrue(opened.Advance())
        self.assertEqual(opened.StaleRecords, 1)
        self.assertEqual(opened.Effective(OWNER, "pressure_brush.hardness"), 0.4)
        self.assertEqual(opened.Effective(OWNER, "active_tool"), "freehand.pressure_brush")

    def test_a_record_out_of_order_ends_the_session(self) -> None:
        opened = self._open()
        self.channels.States.append(self._state(7, 2, 0.4))
        opened.Advance()
        self.assertIs(opened.State, self.session.SessionState.CLOSED)
        self.assertIn("arrived after 0", opened.CloseReason)
        self.assertFalse(opened.Request(OWNER, "pressure_brush.set_hardness", 0.5))

    def test_a_realtime_plane_that_stops_answering_ends_the_session(self) -> None:
        self.channels.Replies.append(None)
        opening = self.session.RealtimePlaneSession(self.channels, 3, replySeconds=1.0, clock=lambda: self.now)
        opening.Advance()
        self.assertIs(opening.State, self.session.SessionState.OPENING)
        self.now = 1.5
        opening.Advance()
        self.assertIs(opening.State, self.session.SessionState.CLOSED)
        self.assertEqual(opening.CloseReason, "the Realtime Plane stopped answering")

    def test_requests_respect_the_window_and_the_latest_value_wins(self) -> None:
        opened = self._open()
        settings = self.profile.SETTINGS
        opened.Request(OWNER, "pressure_brush.set_hardness", 0.1)
        opened.Request(OWNER, "pressure_brush.set_hardness", 0.2)  # replaces the first: nothing was sent
        for index in range(settings.Actions.WindowRecords + 2):
            opened.Request(OWNER, f"pressure_brush.set_value_{index}", float(index))
        self.channels.Replies.append(
            self.frames.EncodeAcknowledgement(7, settings.Actions.Stream, settings.Actions.WindowRecords)
        )
        opened.Advance()
        sent = list(self.frames.SplitFrames(self.channels.Sent[-1]))
        self.assertEqual(len(sent), settings.Actions.WindowRecords)
        firstFrame = self.channels.Sent[-1][: self.frames.HEADER.size + len(sent[0][2])]
        first = self.frames.DecodeRecord(memoryview(firstFrame))
        self.assertEqual(self.profile.DecodeValueAction(first.Payload).Value, 0.2)
        self.assertEqual(opened.Pending(OWNER, "pressure_brush.set_hardness"), 0.2)
        self.channels.Replies.append(self.frames.EncodeAcknowledgement(7, settings.Actions.Stream, 7))
        opened.Advance()  # the acknowledgement arrives; the rest go with the next request
        self.assertIs(opened.State, self.session.SessionState.OPEN, opened.CloseReason)
        self.assertEqual(len(list(self.frames.SplitFrames(self.channels.Sent[-1]))), 3)  # seven asked, four sent
        # A state that says the first action was applied clears only what it covers.
        self.channels.States.append(self._state(7, 1, 0.2, applied=1))
        opened.Advance()
        self.assertIsNone(opened.Pending(OWNER, "pressure_brush.set_hardness"))
        self.assertEqual(opened.Pending(OWNER, "pressure_brush.set_value_0"), 0.0)

    def test_an_action_the_realtime_plane_did_not_acknowledge_ends_the_session(self) -> None:
        opened = self._open()
        opened.Request(OWNER, "pressure_brush.set_hardness", 0.3)
        self.channels.Replies.append(b"")  # answered, but the record was not acknowledged
        opened.Advance()
        opened.Advance()
        self.assertIs(opened.State, self.session.SessionState.CLOSED)
        self.assertEqual(opened.CloseReason, "the Realtime Plane did not accept an action")

    def test_values_no_payload_carries_are_refused(self) -> None:
        opened = self._open()
        self.assertFalse(opened.Request(OWNER, "canvas.clear", None))
        self.assertFalse(opened.Request(OWNER, "pressure_brush.set_hardness", float("inf")))
        self.assertTrue(opened.Request(OWNER, "select_tool", "freehand.pen"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--protocol-dir", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    os.environ["FLEXIBLE_DRAWING_PROTOCOL_DIR"] = str(args.protocol_dir)
    root = types.ModuleType("flexible_drawing")
    root.__path__ = [str(args.extension_dir.resolve())]
    sys.modules["flexible_drawing"] = root
    import flexible_drawing.realtime_plane.session as session

    SessionTests.client = types.SimpleNamespace(session=session)
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
