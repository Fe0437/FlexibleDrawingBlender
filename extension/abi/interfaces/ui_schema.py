"""The UI schema interface, mirroring flexible_drawing_ui_schema.h.

Wraps `fd_ui_schema_api`. The engine describes the UI Flexible Drawing defines - surfaces,
sections, groups and controls, each bound to state it reads and actions it requests - and a host
projects it with its own widgets. Nothing here knows Blender.

The description arrives as self-describing bytes and is decoded by name (see `abi.reflected`), so
each element of the painting workspace carries exactly the fields its C++ record declares: `Id`, `Kind`,
`Control`, `Parent` and `Bindings`, with enumerators as their C++ names such as
"Control" or "Number". A field the engine adds appears here with no edit to this module. The engine's UI
is a set of views: the painting workspace, and each view an editor with a `View` names, whose subject its
state binding holds.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from ..generated import (
    FD_INTERFACE_UI_SCHEMA,
    FD_INTERFACE_UI_SCHEMA_VERSION,
    FD_UI_SCHEMA_VIEW_PAINTING_WORKSPACE,
    fd_ui_schema_api,
)
from ..reflected import Decode, Record
from . import Interface


@dataclass(frozen=True)
class PaintingWorkspaceUiView:
    """The painting workspace view: its elements in depth-first order, every parent before its children.

    A control with a `Setting` is the one an editor makes for each setting of that `Setting.Type` it shows.
    `Label` and `Help` are an element's declared English words, None when it declares none, and an
    editor's `NumberSettings` say how to show the number settings it presents.
    """

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

    def DescribeUiView(self, view: str, subject: str) -> Record:
        """Read one view of the UI for one subject, such as the `graph` view of a tool.

        The engine describes each view and subject once and returns the same answer every time. An editor
        with a `View` names a view; its one state binding holds the subject. Raises EngineError with
        FD_UI_SCHEMA_STATUS_UNKNOWN_VIEW when the engine has no such view or it cannot show that subject.
        """
        data = ctypes.POINTER(ctypes.c_uint8)()
        size = ctypes.c_uint64()
        self._invoke(
            self._entry("describe"),
            view.encode("utf-8"),
            subject.encode("utf-8"),
            ctypes.byref(data),
            ctypes.byref(size),
        )
        return Decode(ctypes.string_at(data, size.value))

    def DescribePaintingWorkspace(self) -> PaintingWorkspaceUiView:
        """Read the painting workspace, the view a host shows first."""
        return PaintingWorkspaceUiView(self.DescribeUiView(FD_UI_SCHEMA_VIEW_PAINTING_WORKSPACE, "").Elements)
