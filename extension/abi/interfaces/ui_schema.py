"""The UI schema interface, mirroring flexible_drawing_ui_schema.h.

Wraps `fd_ui_schema_api`. The engine describes the UI Flexible Drawing defines - surfaces,
sections, groups and controls, each bound to state it reads and actions it requests - and a host
projects it with its own widgets. Nothing here knows Blender.

The description arrives as self-describing bytes and is decoded by name (see `abi.reflected`), so
each element carries exactly the fields the engine's C++ projection declares: `Id`, `Kind`,
`Control`, `Parent`, `Bindings` and `Choices`, with enumerators as their C++ names such as
"Control" or "Number". A field the engine adds appears here with no edit to this module.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from ..generated import FD_INTERFACE_UI_SCHEMA, FD_INTERFACE_UI_SCHEMA_VERSION, fd_ui_schema_api
from ..reflected import Decode, Record
from . import Interface


@dataclass(frozen=True)
class UiSchema:
    """The engine's whole UI: elements in depth-first order, every parent before its children."""

    Elements: tuple[Record, ...]

    def ChildrenOf(self, index: int) -> tuple[int, ...]:
        """Indices of the elements directly inside element `index`, in order."""
        return tuple(position for position, element in enumerate(self.Elements) if element.Parent == index)

    def Surfaces(self) -> tuple[int, ...]:
        """Indices of the top-level surfaces."""
        return tuple(position for position, element in enumerate(self.Elements) if element.Parent is None)


class UiSchemaInterface(Interface):
    """Describes the UI the engine defines, for a host to project."""

    NAME = FD_INTERFACE_UI_SCHEMA
    VERSION = FD_INTERFACE_UI_SCHEMA_VERSION
    TABLE = fd_ui_schema_api
    ATTRIBUTE = "UiSchema"

    def Describe(self) -> UiSchema:
        """Read the engine's UI. The engine builds it once; every call returns the same description."""
        data = ctypes.POINTER(ctypes.c_uint8)()
        size = ctypes.c_uint64()
        self._invoke(self._entry("describe"), ctypes.byref(data), ctypes.byref(size))
        return UiSchema(Decode(ctypes.string_at(data, size.value)).Elements)
