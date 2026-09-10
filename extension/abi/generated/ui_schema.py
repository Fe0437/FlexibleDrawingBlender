"""flexible_drawing_ui_schema.h in Python. Generated: do not edit — see this package's __init__.

The ui_schema interface: its table, its records, its constants, and its host values.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from .bootstrap import fd_engine, fd_engine_status


# Status codes
# Zero is success. The bootstrap owns 0-999; each interface owns a block from 1000 up.
FD_UI_SCHEMA_STATUS_UNRESOLVED = 1200


# Interfaces
# Names and generations for fd_engine_get_interface.
FD_INTERFACE_UI_SCHEMA = "ui_schema"
FD_INTERFACE_UI_SCHEMA_VERSION = 1


# Constants
# Every other value the header pins, which a host compares against by number.
FD_UI_BINDING_ACTION = 2
FD_UI_BINDING_CAPABILITY = 3
FD_UI_BINDING_STATE = 1
FD_UI_CONTROL_BOOLEAN = 2
FD_UI_CONTROL_CHOICE = 5
FD_UI_CONTROL_COMMAND = 1
FD_UI_CONTROL_INTEGER = 3
FD_UI_CONTROL_NONE = 0
FD_UI_CONTROL_NUMBER = 4
FD_UI_CONTROL_TEXT = 6
FD_UI_ELEMENT_CONTROL = 5
FD_UI_ELEMENT_EDITOR = 4
FD_UI_ELEMENT_GROUP = 3
FD_UI_ELEMENT_SECTION = 2
FD_UI_ELEMENT_SURFACE = 1
FD_UI_NO_PARENT = 18446744073709551615
FD_UI_VALUE_BOOLEAN = 1
FD_UI_VALUE_IDENTITY = 5
FD_UI_VALUE_INTEGER = 2
FD_UI_VALUE_NONE = 0
FD_UI_VALUE_NUMBER = 3
FD_UI_VALUE_TEXT = 4


class fd_ui_binding(ctypes.Structure):
    """Array-element record: frozen layout, because callers stride by their own sizeof."""

    _fields_ = [
        ("owner", ctypes.c_char_p),
        ("id", ctypes.c_char_p),
        ("role", ctypes.c_uint32),
        ("value_type", ctypes.c_uint32),
    ]


class fd_ui_choice(ctypes.Structure):
    """Array-element record: frozen layout, because callers stride by their own sizeof."""

    _fields_ = [
        ("element", ctypes.c_uint64),
        ("identity", ctypes.c_char_p),
    ]


class fd_ui_element(ctypes.Structure):
    """Array-element record: frozen layout, because callers stride by their own sizeof."""

    _fields_ = [
        ("id", ctypes.c_char_p),
        ("kind", ctypes.c_uint32),
        ("control_role", ctypes.c_uint32),
        ("parent", ctypes.c_uint64),
        ("first_binding", ctypes.c_uint64),
        ("binding_count", ctypes.c_uint64),
    ]


class fd_ui_schema(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("elements", ctypes.POINTER(fd_ui_element)),
        ("element_count", ctypes.c_uint64),
        ("bindings", ctypes.POINTER(fd_ui_binding)),
        ("binding_count", ctypes.c_uint64),
        ("choices", ctypes.POINTER(fd_ui_choice)),
        ("choice_count", ctypes.c_uint64),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


class fd_ui_schema_api(ctypes.Structure):
    """Engine-owned table; struct_size reports how many entry points it populated."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("describe", ctypes.CFUNCTYPE(fd_engine_status, fd_engine, ctypes.POINTER(fd_ui_schema))),
    ]


@dataclass(frozen=True)
class UiBinding:
    """Host-side value of one `fd_ui_binding`, detached from the engine's memory."""

    #: Package or service that owns the contract, such as `presentation.tool_ui`.
    Owner: str
    #: Contract identity within its owner, such as `pressure_brush.set_hardness`.
    Id: str
    #: One `FD_UI_BINDING_` value: how the host may use the contract.
    Role: int
    #: One `FD_UI_VALUE_` value: the shape of the value it carries.
    ValueType: int

    @classmethod
    def FromRecord(cls, record: fd_ui_binding) -> "UiBinding":
        """Copy an engine-filled record into an immutable host value."""
        return cls(
            (record.owner or b"").decode("utf-8"), (record.id or b"").decode("utf-8"), int(record.role),
            int(record.value_type)
        )

    def ToRecord(self) -> fd_ui_binding:
        """Marshal this value into a fresh `fd_ui_binding`, sized and ready to hand across."""
        return fd_ui_binding(
            self.Owner.encode("utf-8"), self.Id.encode("utf-8"), int(self.Role), int(self.ValueType)
        )


@dataclass(frozen=True)
class UiChoice:
    """Host-side value of one `fd_ui_choice`, detached from the engine's memory."""

    #: Index of the choice control this identity belongs to.
    Element: int
    #: The identity, sent as the control's action value; engine-owned UTF-8.
    Identity: str

    @classmethod
    def FromRecord(cls, record: fd_ui_choice) -> "UiChoice":
        """Copy an engine-filled record into an immutable host value."""
        return cls(int(record.element), (record.identity or b"").decode("utf-8"))

    def ToRecord(self) -> fd_ui_choice:
        """Marshal this value into a fresh `fd_ui_choice`, sized and ready to hand across."""
        return fd_ui_choice(int(self.Element), self.Identity.encode("utf-8"))


@dataclass(frozen=True)
class UiElement:
    """Host-side value of one `fd_ui_element`, detached from the engine's memory."""

    #: Stable identity, unique in the schema; engine-owned UTF-8. Host profiles name it.
    Id: str
    #: One `FD_UI_ELEMENT_` value.
    Kind: int
    #: One `FD_UI_CONTROL_` value for a control; `FD_UI_CONTROL_NONE` otherwise.
    ControlRole: int
    #: Index of the containing element; FD_UI_NO_PARENT for a surface, which has none.
    Parent: int
    #: Index of this element's first binding in the schema's binding array.
    FirstBinding: int
    #: How many bindings follow `first_binding`: none for a container.
    BindingCount: int

    @classmethod
    def FromRecord(cls, record: fd_ui_element) -> "UiElement":
        """Copy an engine-filled record into an immutable host value."""
        return cls(
            (record.id or b"").decode("utf-8"), int(record.kind), int(record.control_role), int(record.parent),
            int(record.first_binding), int(record.binding_count)
        )

    def ToRecord(self) -> fd_ui_element:
        """Marshal this value into a fresh `fd_ui_element`, sized and ready to hand across."""
        return fd_ui_element(
            self.Id.encode("utf-8"), int(self.Kind), int(self.ControlRole), int(self.Parent),
            int(self.FirstBinding), int(self.BindingCount)
        )
