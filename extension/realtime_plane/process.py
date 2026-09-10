"""Starting, finding and stopping the Realtime Plane process.

The Realtime Plane is a separate program with its own window and its own pen input. It outlives the
host that started it: a host that quits or crashes leaves it painting, and the next host finds it
again instead of starting a second one. So a host never owns the process the way it owns a child.
It reads a small state file that says which process is the Realtime Plane, and the only way the
process ends is an explicit `Stop`.

Every host of one user talks to the same Realtime Plane through the same service names, so the
names are fixed per user rather than chosen per launch. The state file records them anyway, so a
host can tell it found the process it expects.

A process identity is its PID and its start time together: a PID alone can be reused by an
unrelated program after the Realtime Plane exits, and a host must never stop that program.

```python
program = BundledProgram(extensionDirectory / "realtime_plane" / "bin")
scope = Scope()
running = Attach(StateDirectory(scope)) or Start(program, EndpointsFor(scope), StateDirectory(scope))
...
running.Stop()
```
"""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
from typing import NamedTuple

#: The executable's name inside a package's Realtime Plane directory.
EXECUTABLE_NAME = "flexible_drawing_realtime_plane"
#: A whole command line that replaces the Realtime Plane; see `ConfiguredProgram`.
COMMAND_VARIABLE = "FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND"
#: Names the scope whose Realtime Plane a host uses; see `Scope`.
SCOPE_VARIABLE = "FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE"
_STATE_FILE = "realtime_plane.json"
_LOG_FILE = "realtime_plane.log"
_STOP_GRACE_SECONDS = 5.0
_STOP_POLL_SECONDS = 0.05


class Endpoints(NamedTuple):
    """The iceoryx2 services a host and the Realtime Plane share, one per channel."""

    Control: str
    State: str
    Tiles: str
    Results: str

    def Arguments(self) -> tuple[str, ...]:
        """The command-line options that tell the Realtime Plane these names."""
        return (
            "--control-service",
            self.Control,
            "--state-service",
            self.State,
            "--tile-service",
            self.Tiles,
            "--result-service",
            self.Results,
        )


def Scope() -> str:
    """Whose Realtime Plane this is: the user's, unless `FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE` says.

    A test sets the variable, so its Realtime Plane is never the one the person at the machine uses.
    """
    scope = os.environ.get(SCOPE_VARIABLE) or getpass.getuser()
    return re.sub(r"[^A-Za-z0-9_-]", "_", scope) or "user"


def EndpointsFor(scope: str) -> Endpoints:
    """The fixed service names of one scope's Realtime Plane; every host in that scope finds them."""
    prefix = f"flexible-drawing/{scope}/realtime-plane"
    return Endpoints(f"{prefix}/control", f"{prefix}/state", f"{prefix}/tiles", f"{prefix}/results")


def StateDirectory(scope: str) -> Path:
    """Where one scope's state file lives: the user's own application data, shared by every host."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Flexible Drawing"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Flexible Drawing"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "flexible_drawing"
    return base / "realtime_plane" / scope


@dataclass(frozen=True)
class Program:
    """How to run the Realtime Plane: the executable, and any arguments that come before the services."""

    Command: tuple[str, ...]


def ConfiguredProgram(bundled: Path, override: str = "") -> Program:
    """The Realtime Plane to run: `FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND`, else `override`, else `bundled`.

    The variable is a whole command line, so a test can run a stand-in; `override` is one executable,
    which a person picks while developing the Realtime Plane.
    """
    command = os.environ.get(COMMAND_VARIABLE)
    if command:
        return Program(tuple(shlex.split(command)))
    if override:
        return Program((override,))
    return BundledProgram(bundled)


def BundledProgram(directory: Path) -> Program:
    """The Realtime Plane a package carries in `directory`.

    An extension installer may extract files without their permissions, so the executable is made
    executable again here, once, before it is ever run.
    """
    executable = directory / EXECUTABLE_NAME
    if executable.is_file() and not os.access(executable, os.X_OK):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return Program((str(executable),))


def _startTime(pid: int) -> str | None:
    """When process `pid` started, as the system reports it; None when there is no such process."""
    completed = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False, timeout=5
    )
    started = completed.stdout.strip()
    return started if completed.returncode == 0 and started else None


class RealtimePlaneProcess:
    """One running Realtime Plane, started by this host or found through the state file."""

    def __init__(self, pid: int, started: str, endpoints: Endpoints, stateDirectory: Path, child: object = None):
        self.Pid = pid
        self.Endpoints = endpoints
        self._started = started
        self._stateDirectory = stateDirectory
        self._child = child  # the Popen, when this host started it: only a parent can reap it

    def Alive(self) -> bool:
        """Whether the process is still running. Cheap enough to ask on every host timer tick."""
        if self._child is not None:
            return self._child.poll() is None
        try:
            # A host that started it and then let go is still its parent, and an exited child it
            # never reaped still answers signals; reaping it here is what lets it count as ended.
            if os.waitpid(self.Pid, os.WNOHANG)[0] == self.Pid:
                return False
        except ChildProcessError:
            pass  # someone else's child: only a signal can tell
        try:
            os.kill(self.Pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # it exists; it is simply not ours to signal
        return True

    def Stop(self) -> None:
        """End the process, politely first, and forget it. A process that already ended is fine."""
        if self.Alive() and _startTime(self.Pid) == self._started:
            os.kill(self.Pid, signal.SIGTERM)
            deadline = time.monotonic() + _STOP_GRACE_SECONDS
            while self.Alive() and time.monotonic() < deadline:
                time.sleep(_STOP_POLL_SECONDS)
            if self.Alive():
                os.kill(self.Pid, signal.SIGKILL)
                deadline = time.monotonic() + _STOP_GRACE_SECONDS
                while self.Alive() and time.monotonic() < deadline:
                    time.sleep(_STOP_POLL_SECONDS)
        if self._child is not None:
            self._child.wait()
        _forget(self._stateDirectory, self.Pid)


def _forget(stateDirectory: Path, pid: int) -> None:
    """Remove the state file if it still names `pid`; a newer process's record stays."""
    path = stateDirectory / _STATE_FILE
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == pid:
            path.unlink()
    except (OSError, ValueError):
        pass


def Attach(stateDirectory: Path) -> RealtimePlaneProcess | None:
    """The Realtime Plane the state file names, if that exact process is still running."""
    try:
        record = json.loads((stateDirectory / _STATE_FILE).read_text(encoding="utf-8"))
        pid, started, endpoints = int(record["pid"]), str(record["started"]), Endpoints(*record["endpoints"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if _startTime(pid) != started:
        _forget(stateDirectory, pid)  # it ended, and the PID may already be someone else's
        return None
    return RealtimePlaneProcess(pid, started, endpoints, stateDirectory)


def Start(program: Program, endpoints: Endpoints, stateDirectory: Path) -> RealtimePlaneProcess:
    """Start the Realtime Plane in its own session, so it outlives this host, and record it.

    Its output goes to a log file beside the state file, because nobody reads the host's terminal.
    Raises `OSError` when the program cannot be started.
    """
    stateDirectory.mkdir(parents=True, exist_ok=True)
    with open(stateDirectory / _LOG_FILE, "wb") as log:
        child = subprocess.Popen(
            [*program.Command, *endpoints.Arguments()],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # a host crash or Ctrl-C does not reach it
            close_fds=True,
        )
    started = _startTime(child.pid) or ""
    record = {"pid": child.pid, "started": started, "endpoints": list(endpoints)}
    staged = stateDirectory / f"{_STATE_FILE}.staged"
    staged.write_text(json.dumps(record), encoding="utf-8")
    staged.replace(stateDirectory / _STATE_FILE)  # a reader never sees half a record
    return RealtimePlaneProcess(child.pid, started, endpoints, stateDirectory, child)
