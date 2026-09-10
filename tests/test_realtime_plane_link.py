#!/usr/bin/env python3
"""Drive the extension's Realtime Plane client against a Realtime Plane that paints, over iceoryx2.

The client is the host-neutral `realtime_plane` package, run here in plain Python exactly as Blender
runs it. The Realtime Plane is its own headless host-session peer behind the Realtime Plane's
command line (`realtime_plane_stand_in.py`), painting a continuous stroke with a fake pen. Every case
uses its own scope, so it never touches the Realtime Plane of the person at the machine.

The cases: the canvas opens and closes again and again; a crashed Realtime Plane is reported and a
new one started; a crashed host leaves the Realtime Plane running for the next host; records of a
replaced session are dropped on both ends; a setting is pending until it takes effect; and a slow
host keeps seeing the canvas move during a long stroke.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zipfile

TIMEOUT_S = 15.0
OWNER = "presentation.tool_ui"
SET_HARDNESS = "pressure_brush.set_hardness"
HARDNESS = "pressure_brush.hardness"


class Environment:
    """What the cases share: the client package, and how to start the stand-in."""

    extension: Path
    peer: Path
    packages: Path
    stateRoot: Path
    standIn = Path(__file__).resolve().with_name("realtime_plane_stand_in.py")


def _load(extension: Path) -> types.SimpleNamespace:
    """The client package, imported without the Blender add-on around it."""
    root = types.ModuleType("flexible_drawing")
    root.__path__ = [str(extension)]
    sys.modules["flexible_drawing"] = root
    import flexible_drawing.realtime_plane.link as link
    import flexible_drawing.realtime_plane.process as process
    import flexible_drawing.realtime_plane.session as session

    return types.SimpleNamespace(link=link, process=process, session=session)


def _until(condition: object, advance: object, what: str, interval: float = 0.005) -> float:
    """Advance until `condition()` holds; return how long it took, or fail after the timeout."""
    started = time.monotonic()
    while not condition():
        if time.monotonic() - started > TIMEOUT_S:
            raise AssertionError(f"timed out waiting for {what}")
        advance()
        time.sleep(interval)
    return time.monotonic() - started


class LinkTests(unittest.TestCase):
    client: types.SimpleNamespace

    def setUp(self) -> None:
        self.scope = f"link-test-{os.getpid()}-{self._testMethodName}"
        self.stateDirectory = Environment.stateRoot / self.scope
        self._stateDirectory = self.client.link.StateDirectory
        self.client.link.StateDirectory = lambda _scope: self.stateDirectory
        self.links: list[object] = []

    def tearDown(self) -> None:
        for link in self.links:
            link.Reattach()  # a case may have let go of the Realtime Plane; it still has to end
            link.Stop()
        self.client.link.StateDirectory = self._stateDirectory
        shutil.rmtree(self.stateDirectory, ignore_errors=True)

    def _program(self) -> object:
        command = (sys.executable, str(Environment.standIn), "--peer", str(Environment.peer))
        return self.client.process.Program(command)

    def _link(self) -> object:
        link = self.client.link.RealtimePlaneLink(self._program, self.scope)
        self.links.append(link)
        return link

    def _connected(self, link: object) -> None:
        connected = self.client.link.LinkState.CONNECTED
        _until(lambda: link.State is connected, link.Advance, "a session")
        _until(lambda: link.Effective(OWNER, HARDNESS) is not None, link.Advance, "the first tool state")

    def test_open_and_close_repeatedly_reuse_one_process(self) -> None:
        link = self._link()
        link.Open()
        self._connected(link)
        pid = link.Process.Pid
        for _ in range(5):
            link.Detach()  # a host closing, or the add-on disabled: the Realtime Plane keeps running
            self.assertIs(link.State, self.client.link.LinkState.STOPPED)
            link.Open()
            self.assertEqual(link.Message, "attached to the running Realtime Plane")
            self._connected(link)
            self.assertEqual(link.Process.Pid, pid)
        link.Stop()
        self.assertFalse(link.Reattach(), "a stopped Realtime Plane is forgotten")

    def test_a_crashed_realtime_plane_is_reported_and_a_new_one_starts(self) -> None:
        link = self._link()
        link.Open()
        self._connected(link)
        crashed = link.Process.Pid
        os.killpg(crashed, signal.SIGKILL)  # the whole process group, as a crash would end it
        _until(lambda: link.State is self.client.link.LinkState.STOPPED, link.Advance, "the crash to be noticed")
        self.assertEqual(link.Message, "the Realtime Plane exited")
        self.assertFalse(link.Available)
        self.assertFalse(link.Request(OWNER, SET_HARDNESS, 0.5), "nothing is requested of a dead process")
        link.Open()
        self.assertEqual(link.Message, "started the Realtime Plane")
        self.assertNotEqual(link.Process.Pid, crashed)
        self._connected(link)

    def test_a_crashed_host_leaves_the_realtime_plane_for_the_next_one(self) -> None:
        first = self._link()
        first.Open()
        self._connected(first)
        pid = first.Process.Pid
        # A host that dies holding an open session: it never closes it and never lets go.
        crash = (
            "import sys, types, time\n"
            "from pathlib import Path\n"
            f"root = types.ModuleType('flexible_drawing'); root.__path__ = [{str(Environment.extension)!r}]\n"
            "sys.modules['flexible_drawing'] = root\n"
            "import flexible_drawing.realtime_plane.link as client\n"
            f"client.StateDirectory = lambda _scope: Path({str(self.stateDirectory)!r})\n"
            f"link = client.RealtimePlaneLink(lambda: None, {self.scope!r})\n"
            "assert link.Reattach()\n"
            "started = time.monotonic()\n"
            "while link.State is not client.LinkState.CONNECTED and time.monotonic() - started < 15:\n"
            "    link.Advance(); time.sleep(0.005)\n"
            "print('CONNECTED' if link.State is client.LinkState.CONNECTED else 'NOT CONNECTED', flush=True)\n"
            "import os; os._exit(0)\n"
        )
        first.Detach()
        environment = {**os.environ, "PYTHONPATH": str(Environment.packages)}
        crashed = subprocess.run(
            [sys.executable, "-c", crash], env=environment, capture_output=True, text=True, timeout=60
        )
        self.assertIn("CONNECTED", crashed.stdout, crashed.stderr)
        self.assertNotIn("NOT CONNECTED", crashed.stdout, crashed.stderr)
        second = self._link()
        self.assertTrue(second.Reattach(), "the Realtime Plane outlived the host that crashed")
        self.assertEqual(second.Process.Pid, pid)
        self._connected(second)

    def test_the_realtime_plane_refuses_a_replaced_session_and_keeps_the_new_one(self) -> None:
        link = self._link()
        link.Open()
        self._connected(link)
        endpoints = self.client.process.EndpointsFor(self.scope)
        link.Detach()
        session = self.client.session
        # A host that dies holding session 1; the next host opens session 2 on ports of its own.
        dying = session.RealtimePlaneSession(self.client.link.Iceoryx2Channels(endpoints), 1)
        _until(lambda: dying.State is session.SessionState.OPEN, dying.Advance, "the first session")
        dying = None  # dropped without closing, as a crash drops it
        channels = self.client.link.Iceoryx2Channels(endpoints)
        new = session.RealtimePlaneSession(channels, 2)
        _until(lambda: new.Effective(OWNER, HARDNESS) is not None, new.Advance, "the new session's tool state")
        # A late action of session 1 is answered by closing session 1, and changes nothing.
        settings, frames = session.Profile.SETTINGS, session.Frames
        action = session.Profile.EncodeValueAction(session.Profile.ValueAction(OWNER, SET_HARDNESS, 0.9))
        reply = channels.Send(
            frames.EncodeRecord(1, settings.Actions.Stream, 1, 0, settings.ValueActionPayload, action)
        )
        deadline = time.monotonic() + TIMEOUT_S
        while (answer := reply.Take()) is None:
            self.assertLess(time.monotonic(), deadline, "the replaced session was never answered")
            time.sleep(0.005)
        ((kind, refused, _body),) = frames.SplitFrames(answer)
        self.assertEqual((kind, refused), (frames.SESSION_CLOSE, 1))
        for _ in range(20):
            new.Advance()
            time.sleep(0.01)
        self.assertIs(new.State, session.SessionState.OPEN, new.CloseReason)
        self.assertNotEqual(new.Effective(OWNER, HARDNESS), 0.9)
        new.Close()

    def test_a_setting_is_pending_until_it_takes_effect(self) -> None:
        link = self._link()
        link.Open()
        self._connected(link)
        before = link.Effective(OWNER, HARDNESS)
        self.assertTrue(link.Request(OWNER, SET_HARDNESS, 0.8))
        self.assertEqual(link.Pending(OWNER, SET_HARDNESS), 0.8)
        self.assertEqual(link.Effective(OWNER, HARDNESS), before, "nothing took effect before it was sent")
        _until(lambda: link.Pending(OWNER, SET_HARDNESS) is None, link.Advance, "the setting to take effect")
        self.assertEqual(link.Effective(OWNER, HARDNESS), 0.8)
        # A slider dragged before anything was sent sends only where it ended.
        for value in (0.1, 0.2, 0.3):
            link.Request(OWNER, SET_HARDNESS, value)
        _until(lambda: link.Pending(OWNER, SET_HARDNESS) is None, link.Advance, "the last value")
        self.assertEqual(link.Effective(OWNER, HARDNESS), 0.3)
        self.assertTrue(link.Request(OWNER, "select_tool", "freehand.pen"))
        _until(lambda: link.Effective(OWNER, "active_tool") == "freehand.pen", link.Advance, "the tool")
        self.assertFalse(link.Request(OWNER, SET_HARDNESS, float("nan")), "a value no payload carries")

    def test_a_slow_host_sees_the_canvas_move_through_a_long_stroke(self) -> None:
        link = self._link()
        link.Open()
        self._connected(link)
        # A host whose timer runs late: 50 ms between turns, while the stroke goes on.
        revisions: list[int] = []
        changedTurns = 0
        for _ in range(40):
            if link.Advance():
                changedTurns += 1
            revisions.append(link.Session.Mirror.CanvasRevision)
            time.sleep(0.05)
        self.assertIs(link.State, self.client.link.LinkState.CONNECTED, link.Message)
        self.assertEqual(revisions, sorted(revisions), "the canvas went back")
        self.assertGreater(len(set(revisions)), 10, f"the canvas barely moved: {revisions}")
        self.assertGreater(changedTurns, 10)
        self.assertTrue(link.Session.Mirror.Tiles, "no tile reached the host")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--protocol-dir", type=Path, required=True)
    parser.add_argument("--peer", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    os.environ["FLEXIBLE_DRAWING_PROTOCOL_DIR"] = str(args.protocol_dir)
    Environment.extension = args.extension_dir.resolve()
    Environment.peer = args.peer
    with tempfile.TemporaryDirectory(prefix="realtime-plane-link-") as packages:
        for wheel in sorted(args.wheel_dir.glob("*.whl")):
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(packages)
        sys.path.insert(0, packages)
        Environment.packages = Path(packages)
        Environment.stateRoot = Path(packages) / "state"
        LinkTests.client = _load(Environment.extension)
        program = unittest.main(argv=[sys.argv[0], *remaining], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
