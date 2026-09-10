"""One module per engine interface. New interfaces go here.

Each module in this package wraps one table from the C interface, and mirrors the engine's own
`private/<name>_table.cpp`. A module says which table it wants and which of its entry points it
calls; how a table is read and called lives here in the `Interface` base class and is written once.

Nothing has to be told about a new module. `abi/registry.py` finds every `Interface` subclass in this
package, and the engine publishes each one under the name its class gives.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING, Any, ClassVar

from ..errors import EngineError
from ..generated import FD_ENGINE_STATUS_OK

if TYPE_CHECKING:  # Only for the annotation: importing it for real would close a cycle.
    from ..engine import EngineBridge


def MemberEnd(structure: type, member: str) -> int:
    """Byte offset just past a table member, which is what struct_size must reach to reveal it."""
    field = getattr(structure, member)
    return int(field.offset) + int(field.size)


class Interface:
    """One engine-owned C table, fetched once and bound to typed Python methods.

    Subclass it once per FD_INTERFACE_* table, in a module of its own. The subclass says which table
    it wants and which of its entry points it calls, then wraps each one in a method that takes and
    returns ordinary Python values instead of ctypes records:

    ```python
    from .generated import (
        FD_INTERFACE_BRUSH, FD_INTERFACE_BRUSH_VERSION, BrushSettings, fd_brush_api, fd_brush_settings
    )
    from .interface import Interface


    class BrushInterface(Interface):
        '''Define and apply brushes.'''

        NAME = FD_INTERFACE_BRUSH
        VERSION = FD_INTERFACE_BRUSH_VERSION
        TABLE = fd_brush_api
        ATTRIBUTE = "Brushes"

        def Define(self, settings: BrushSettings) -> None:
            '''Register a brush definition with the engine.'''
            record = settings.ToRecord()
            self._invoke(self._entry("define"), ctypes.byref(record))
    ```

    That is the whole change. The engine finds this class by itself and publishes it under
    `ATTRIBUTE`, so `engine.Brushes.Define(...)` works with no edit to `engine.py`. Creating it reads
    the table and checks that the engine really provides every name in `ENTRY_POINTS`, so an engine
    older than this add-on fails at startup with a message naming the entry point it lacks.

    The entry point names are not written out anywhere: `ENTRY_POINTS` is filled in from the table.
    Declare it by hand only to ask for fewer than the table has, which is how a wrapper keeps working
    against an engine that predates an entry point it does not call.
    """

    #: Interface name and generation passed to fd_engine_get_interface.
    NAME: ClassVar[str]
    VERSION: ClassVar[int]
    #: The generated ctypes mirror of this table.
    TABLE: ClassVar[type]
    #: Entry points this wrapper needs. Filled in from TABLE, so the names are not written twice.
    #: Set it by hand only to ask for fewer than the table has — see __init_subclass__.
    ENTRY_POINTS: ClassVar[tuple[str, ...]]
    #: The name this interface is reached by, as in `engine.Documents`. The engine reads it from
    #: here, so adding an interface never means editing the engine.
    ATTRIBUTE: ClassVar[str]

    def __init_subclass__(cls, **keywords: object) -> None:
        """Fill in ENTRY_POINTS from the table, so no subclass lists the member names again.

        The default is every entry point the table has. Set ENTRY_POINTS by hand only to ask for
        fewer: a wrapper that must keep working against an engine older than the header it was built
        against leaves out the entry points that engine will not have.
        """
        super().__init_subclass__(**keywords)
        table = vars(cls).get("TABLE")
        if table is not None and "ENTRY_POINTS" not in vars(cls):
            cls.ENTRY_POINTS = tuple(name for name, _ in table._fields_ if name != "struct_size")

    def __init__(self, engine: EngineBridge) -> None:
        self._engine = engine
        self._table = engine.Table(self.NAME, self.VERSION, self.TABLE, self.ENTRY_POINTS)
        # Read once, here, not on every call. Reading a field of a ctypes structure builds a new
        # function-pointer object each time, which is wasted work on a path used for every stroke.
        self._entryPoints = {name: getattr(self._table, name) for name in self.ENTRY_POINTS}

    def _entry(self, member: str) -> Any:
        """One entry point, by the name it has in the C table.

        Only names listed in ENTRY_POINTS can be reached, so a typo fails here with a clear message
        rather than further along.
        """
        if member not in self._entryPoints:
            raise EngineError(
                None,
                f"'{member}' is not listed in {type(self).__name__}.ENTRY_POINTS, so it was never "
                f"read from the engine's '{self.NAME}' table",
            )
        return self._entryPoints[member]

    def _invoke(self, entryPoint: Any, *arguments: object) -> None:
        """Call one entry point and translate a non-zero status into the engine's own diagnostic.

        The engine handle is supplied here, so a caller passes only the arguments after it. A
        non-zero status becomes an EngineError carrying that status, which callers compare against
        the generated FD_*_STATUS_* constants to recover from a specific failure.
        """
        status = int(entryPoint(self._engine.Handle, *arguments))
        if status != FD_ENGINE_STATUS_OK:
            raise self._engine.Failure(status, f"the {self.NAME} interface reported status {status}")

    @classmethod
    def Reaches(cls, table: object, member: str) -> bool:
        """Whether the engine populated far enough to have this member. See fd_sized_records.

        For an entry point appended after this host's baseline, which an older engine may not serve:
        list it in `ENTRY_POINTS` only if the wrapper cannot work without it, and otherwise ask here
        before calling. The C++ equivalent is `fd::Reaches` in flexible_drawing_engine.hpp.
        """
        return int(table.struct_size) >= MemberEnd(cls.TABLE, member)


def FetchTable(
    library: ctypes.CDLL, handle: object, name: str, version: int, structure: type, entryPoints: tuple[str, ...]
) -> object:
    """Fetch one engine-owned table by name and generation and prove it reaches every member used.

    The engine sets `struct_size` to the number of bytes it populated, so an engine older than this
    host serves a shorter table. Checking here means a missing entry point is one legible error at
    startup rather than a null call somewhere later.
    """
    address = ctypes.c_void_p()
    status = int(library.fd_engine_get_interface(handle, name.encode("utf-8"), version, ctypes.byref(address)))
    if status != FD_ENGINE_STATUS_OK:
        raise EngineError(status, f"the engine serves no '{name}' interface of generation {version}")
    table = ctypes.cast(address, ctypes.POINTER(structure)).contents
    for member in entryPoints:
        if int(table.struct_size) < MemberEnd(structure, member):
            raise EngineError(
                status,
                f"the engine's '{name}' table stops at {int(table.struct_size)} bytes and does not "
                f"provide '{member}'; the engine is older than this host",
            )
    return table
