"""The UI schema interface, mirroring flexible_drawing_ui_schema.h.

Wraps `fd_ui_schema_api`. The engine describes the UI Flexible Drawing defines - surfaces,
sections, groups and controls, each bound to state it reads and actions it requests - and a host
projects it with its own widgets. Nothing here knows Blender; the description comes back as plain,
immutable values detached from the engine's memory.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from ..generated import (
    FD_INTERFACE_UI_SCHEMA,
    FD_INTERFACE_UI_SCHEMA_VERSION,
    FD_UI_NO_PARENT,
    UiBinding,
    UiChoice,
    UiElement,
    fd_ui_schema,
    fd_ui_schema_api,
)
from . import Interface


@dataclass(frozen=True)
class UiSchema:
    """The engine's whole UI: elements in depth-first order, the bindings they name, and the
    identities each choice control offers."""

    Elements: tuple[UiElement, ...]
    Bindings: tuple[UiBinding, ...]
    Choices: tuple[UiChoice, ...]

    def ChoicesOf(self, index: int) -> tuple[str, ...]:
        """The identities choice control `index` offers, in the order the engine gave them."""
        return tuple(choice.Identity for choice in self.Choices if choice.Element == index)

    def BindingsOf(self, element: UiElement) -> tuple[UiBinding, ...]:
        """The bindings one element reads, requests or checks, in the order the engine gave them."""
        return self.Bindings[element.FirstBinding : element.FirstBinding + element.BindingCount]

    def ChildrenOf(self, index: int) -> tuple[int, ...]:
        """Indices of the elements directly inside element `index`, in order."""
        return tuple(position for position, element in enumerate(self.Elements) if element.Parent == index)

    def Surfaces(self) -> tuple[int, ...]:
        """Indices of the top-level surfaces."""
        return tuple(position for position, element in enumerate(self.Elements) if element.Parent == FD_UI_NO_PARENT)


class UiSchemaInterface(Interface):
    """Describes the UI the engine defines, for a host to project."""

    NAME = FD_INTERFACE_UI_SCHEMA
    VERSION = FD_INTERFACE_UI_SCHEMA_VERSION
    TABLE = fd_ui_schema_api
    ATTRIBUTE = "UiSchema"

    def Describe(self) -> UiSchema:
        """Read the engine's UI. The engine builds it once; every call returns the same description."""
        schema = fd_ui_schema()
        self._invoke(self._entry("describe"), ctypes.byref(schema))
        elements = tuple(UiElement.FromRecord(schema.elements[index]) for index in range(schema.element_count))
        bindings = tuple(UiBinding.FromRecord(schema.bindings[index]) for index in range(schema.binding_count))
        choices = tuple(UiChoice.FromRecord(schema.choices[index]) for index in range(schema.choice_count))
        return UiSchema(elements, bindings, choices)
