"""The Blender classes this add-on registers, found automatically.

Blender needs a list of classes to register and, in reverse, to unregister. Keeping that list by hand
means every new operator or panel has to be written twice, and forgetting the second half produces a
class that never appears with no error to explain why.

So the list is not kept by hand. `register` imports every module in this package and registers each
Blender class defined there, in the order the classes are written. Adding a button means writing the
class, and nothing else.

This package also holds the engine the add-on lends the UI. Blender creates operator instances
itself, so there is nowhere to pass the engine in; `SetEngine` puts it here and `Engine` reads it
back. The add-on sets it before registering and clears it before stopping the engine, so `poll` can
always check whether there is an engine to talk to.

Some classes cannot be written down, because what they are depends on the engine: the panels and
properties projected from the engine's UI schema. A module that makes such classes defines
`GeneratedClasses()`, and `register` registers what it returns after every written class, in the
order returned, and unregisters them with the rest.

The add-on also lends the Realtime Plane link the same way: `SetRealtimePlane` and `RealtimePlane`.
The projected UI does not ask for the link by name: it asks for its `BindingTarget`, whatever the UI's
bindings act on, which today is the Realtime Plane.
"""

from __future__ import annotations

import importlib
import pkgutil

import bpy

# Blender registers instances of these. A name missing from this build of Blender is skipped, so the
# same code works across versions.
_REGISTRABLE_TYPE_NAMES = (
    "Operator",
    "Panel",
    "Menu",
    "Header",
    "UIList",
    "PropertyGroup",
    "AddonPreferences",
    "Gizmo",
    "GizmoGroup",
)

_engine: object | None = None
_realtimePlane: object | None = None
_registered: list[type] = []


def SetEngine(engine: object | None) -> None:
    """Lend the live engine to the UI, or take it back when the add-on stops."""
    global _engine
    _engine = engine


def Engine() -> object | None:
    """The engine the add-on lent us, or None when there is none. Every `poll` checks this."""
    return _engine


def SetRealtimePlane(link: object | None) -> None:
    """Lend the UI the Realtime Plane link, or take it back when the add-on stops."""
    global _realtimePlane
    _realtimePlane = link


def RealtimePlane() -> object | None:
    """The Realtime Plane link the add-on lent us, or None when there is none."""
    return _realtimePlane


def BindingTarget() -> object | None:
    """What the UI's bindings act on, or None when there is nothing.

    The target answers `Label`, `Available`, `UnavailableReason`, `Request(owner, action, value)`,
    `Pending(owner, action)` and `Effective(owner, state)`, with the owner and identity names the UI
    schema gives each binding.
    """
    return _realtimePlane


def _registrableBases() -> tuple[type, ...]:
    """The Blender base classes this build of Blender offers."""
    found = (getattr(bpy.types, name, None) for name in _REGISTRABLE_TYPE_NAMES)
    return tuple({base for base in found if isinstance(base, type)})


def _modules() -> list[object]:
    """Every module in this package, in alphabetical order."""
    found = sorted(pkgutil.iter_modules(__path__), key=lambda entry: entry.name)
    return [importlib.import_module(f"{__name__}.{entry.name}") for entry in found]


def _declaredClasses() -> list[type]:
    """Every class defined in this package, in a stable order.

    Modules are visited in alphabetical order, and within a module the classes come out in the order
    they are written. That matters when one class refers to another, such as a sub-panel naming its
    parent: write the parent first.
    """
    classes: list[type] = []
    for module in _modules():
        classes += [
            value
            # Defined here, not imported from somewhere else, so a class is registered once and by
            # the package that owns it.
            for value in vars(module).values()
            if isinstance(value, type) and value.__module__ == module.__name__
        ]
    return classes


def RegisteredClasses() -> list[type]:
    """The classes Blender registers by class, such as operators and panels."""
    bases = _registrableBases()
    if not bases:
        return []
    return [found for found in _declaredClasses() if issubclass(found, bases)]


def GeneratedClasses() -> list[type]:
    """The classes the package's modules make at registration, such as the projected UI."""
    classes: list[type] = []
    for module in _modules():
        generate = getattr(module, "GeneratedClasses", None)
        if callable(generate):
            classes += generate()
    return classes


def register() -> None:
    """Register everything in this package with Blender.

    Written classes first, then generated ones, which may name a written operator.
    """
    for found in [*RegisteredClasses(), *GeneratedClasses()]:
        bpy.utils.register_class(found)
        _registered.append(found)


def unregister() -> None:
    """Remove exactly what `register` added, in reverse."""
    while _registered:
        bpy.utils.unregister_class(_registered.pop())
