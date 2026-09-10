"""One engine instance: negotiate the ABI, hold the handle, own the interface wrappers.

This is the whole lifecycle half of the boundary. Domain calls do not live here — they live in one
module per FD_INTERFACE_* table, reached through the properties below.
"""

from __future__ import annotations

from collections.abc import Callable
import ctypes
from pathlib import Path

from .errors import EngineError
from .generated import (
    FD_ABI_VERSION,
    FD_ABI_VERSION_MAJOR,
    FD_ABI_VERSION_MAJOR_OF,
    FD_ABI_VERSION_MINOR,
    FD_ABI_VERSION_MINOR_OF,
    FD_ENGINE_STATUS_OK,
    fd_engine,
    fd_host_api,
    fd_log_callback,
)
from .interfaces import FetchTable
from .library import DiscoverLibrary, LoadLibrary
from .registry import InterfaceTypes

#: Receives (severity, category, message) for every engine diagnostic. See FD_LOG_SEVERITY_*.
LogSink = Callable[[int, str, str], None]


class EngineBridge:
    """A live engine, from `Initialize` to `Shutdown`.

    Two engines share nothing, exactly as on the C side. Every call goes through one of the
    interfaces the engine publishes — `engine.Documents`, `engine.Receivers` — each of which mirrors
    one table in the C interface. The engine finds them itself, so adding one never changes this
    file; see `registry.py`.

    `Open` gives you a running engine: it finds the packaged library, checks that its ABI is one this
    host can speak, creates the instance, and binds every interface. There is no separate
    initialization step to forget.

    ```python
    from flexible_drawing.abi import EngineBridge, FD_RECEIVER_ORIGIN_MEASURED

    with EngineBridge.Open(log=print) as engine:
        document = engine.Documents.Create("Untitled")
        print(document.DocumentId, document.Revision, document.LayerCount)

        receiver = engine.Receivers.Create(seed=42)
        engine.Receivers.BeginContact(receiver.ReceiverId, 1)
        batch = engine.Receivers.Batch()
        batch.Append(
            x=0.0, y=0.0, pressure=0.5, timeNanoseconds=1, sequence=1,
            origin=FD_RECEIVER_ORIGIN_MEASURED,
        )
        print(engine.Receivers.Submit(receiver.ReceiverId, 1, 1, batch).Revision)

        engine.Documents.Close(document.DocumentId)
    ```

    A host whose engine outlives one scope — a Blender add-on, where `register` opens it and
    `unregister` closes it — calls `Shutdown` itself instead of using `with`.

    `Shutdown` invalidates every table the engine published, so nothing obtained from it may be used
    afterwards; the properties below refuse rather than let that happen. `Open` locates the library
    beside this package, or wherever FLEXIBLE_DRAWING_ENGINE_LIBRARY points; `FromLibrary` takes one
    already loaded, which is how the tests reach a build tree.

    Not thread-safe to *open or shut down* concurrently with a call in flight: the engine cannot
    detect that. Individual entry points declare their own synchronization class in the C headers.
    """

    def __init__(self, library: ctypes.CDLL, log: LogSink | None = None) -> None:
        self._library = library
        self._handle: object | None = None
        self._grantedAbi = 0
        # Set before anything else can look an interface up; see __getattr__.
        self._interfaces: dict[str, object] = {}
        self._logSink = log
        # Held for the engine's lifetime: ctypes frees a trampoline that goes out of scope, and the
        # engine would then call into freed memory.
        self._logTrampoline = fd_log_callback(self._dispatchLog) if log is not None else fd_log_callback()
        self._hostApi = fd_host_api(None, self._logTrampoline)

    @classmethod
    def Open(cls, extensionRoot: Path | None = None, log: LogSink | None = None) -> EngineBridge:
        """Find the native engine, load it, and return a running instance.

        `extensionRoot` defaults to the package this module ships in, which is where a packaged
        extension carries the library; pass one only to load an extension installed elsewhere. To
        point at a build tree, set FLEXIBLE_DRAWING_ENGINE_LIBRARY instead — see `DiscoverLibrary`.

        `log` receives every engine diagnostic as `(severity, category, message)`; severity is one
        of the FD_LOG_SEVERITY_* values. The engine may call it from any thread it owns, so it must
        be thread-safe and must not call back into the engine. Passing None discards diagnostics at
        no cost.

        Raises EngineError if the library is missing, implements an ABI this host cannot speak,
        refuses to create an instance, or serves a table too old to carry an entry point this host
        calls. All of those are startup failures with a legible message, never a late crash.
        """
        root = extensionRoot if extensionRoot is not None else Path(__file__).resolve().parent.parent
        return cls.FromLibrary(LoadLibrary(DiscoverLibrary(root)), log)

    @classmethod
    def FromLibrary(cls, library: ctypes.CDLL, log: LogSink | None = None) -> EngineBridge:
        """Return a running instance on an already-loaded library. See `Open` for the usual path."""
        engine = cls(library, log)
        engine._start()
        return engine

    def _start(self) -> None:
        """Negotiate the ABI, create the engine, and bind every interface this host calls."""
        # Queried first so a mismatch is a legible error rather than whatever the engine does with
        # an argument list it does not recognize. While the major is 0 the match must be exact.
        available = int(self._library.fd_engine_abi_version())
        if available != FD_ABI_VERSION:
            raise EngineError(
                None,
                f"the engine implements ABI {FD_ABI_VERSION_MAJOR_OF(available)}."
                f"{FD_ABI_VERSION_MINOR_OF(available)}, which cannot serve this host's "
                f"{FD_ABI_VERSION_MAJOR}.{FD_ABI_VERSION_MINOR}",
            )
        granted = ctypes.c_uint32(0)
        handle = fd_engine()
        status = int(
            self._library.fd_engine_create(
                FD_ABI_VERSION, ctypes.byref(self._hostApi), ctypes.byref(granted), ctypes.byref(handle)
            )
        )
        if status != FD_ENGINE_STATUS_OK:
            # No instance exists yet, so the diagnostic is this thread's creation error.
            raise self.Failure(status, "the engine could not be created")
        self._handle = handle
        self._grantedAbi = int(granted.value)
        # Every interface wrapper in this package, found rather than listed. Each is read once and
        # kept: a table exists to make calls cheap, not to be looked up again and again.
        self._interfaces = {found.ATTRIBUTE: found(self) for found in InterfaceTypes()}

    def __enter__(self) -> EngineBridge:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.Shutdown()

    def Shutdown(self) -> None:
        """Destroy the engine. Every table and entry point it published dies with it.

        Idempotent, so a host may call it on a failure path that does not know how far startup got.
        """
        # Dropped before the handle. An entry point that outlives the engine is not an error, it is
        # a call into freed memory, so nothing may still be reachable once destroy has run.
        self._interfaces = {}
        handle, self._handle = self._handle, None
        self._grantedAbi = 0
        if handle is not None:
            self._library.fd_engine_destroy(handle)

    def Version(self) -> str:
        """The engine's semantic version, which is independent of the ABI version."""
        return self._library.fd_engine_version_string().decode("utf-8")

    @property
    def GrantedAbi(self) -> tuple[int, int]:
        """Major/minor the engine agreed to serve. Valid only after `Initialize`."""
        return FD_ABI_VERSION_MAJOR_OF(self._grantedAbi), FD_ABI_VERSION_MINOR_OF(self._grantedAbi)

    def __getattr__(self, name: str) -> object:
        """Reach an interface by the name it published, as in `engine.Documents.Create(...)`.

        Python only calls this when normal attribute lookup fails, so a running engine costs one
        dictionary lookup and nothing else. Asking for a real interface while the engine is not
        running gives an error that says so, rather than a bare AttributeError.
        """
        interfaces = self.__dict__.get("_interfaces") or {}
        if name in interfaces:
            return interfaces[name]
        if name in {found.ATTRIBUTE for found in InterfaceTypes()}:
            raise EngineError(None, f"the Flexible Drawing engine is not running, so '{name}' is unavailable")
        raise AttributeError(name)

    @property
    def Handle(self) -> object:
        """The opaque `fd_engine *` every entry point takes as its first argument."""
        return self._require(self._handle)

    def Table(self, name: str, version: int, structure: type, entryPoints: tuple[str, ...]) -> object:
        """Fetch one engine-owned interface table. Called by `Interface`, not by hosts."""
        return FetchTable(self._library, self.Handle, name, version, structure, entryPoints)

    def Failure(self, status: int, fallback: str) -> EngineError:
        """Build the error for a failed call, preferring the engine's own recorded diagnostic."""
        recorded = self._library.fd_engine_last_error(self._handle)
        return EngineError(status, recorded.decode("utf-8", errors="replace") if recorded else fallback)

    @staticmethod
    def _require(value: object) -> object:
        if value is None:
            raise EngineError(None, "the Flexible Drawing engine is not initialized")
        return value

    def _dispatchLog(self, _userData: object, severity: int, category: bytes, message: bytes) -> None:
        """Hand one engine record to the host's sink. Called from any thread the engine owns."""
        sink = self._logSink
        if sink is not None:
            sink(int(severity), category.decode("utf-8", errors="replace"), message.decode("utf-8", errors="replace"))
