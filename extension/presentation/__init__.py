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

A class that says `RequiresInProcessReceiver = True` is registered only when Blender is hosting a
painting receiver of its own. The external Realtime Plane owns its native input, so its canvas must
not acquire a Blender paint tool that would send it pen events it never asked for; leaving the class
unregistered is what makes that structural rather than a rule somebody has to remember.
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
_inProcessReceiver = False
_registered: list[type] = []
_registeredTools: list[type] = []


def SetEngine(engine: object | None) -> None:
    """Lend the live engine to the UI, or take it back when the add-on stops."""
    global _engine
    _engine = engine


def Engine() -> object | None:
    """The engine the add-on lent us, or None when there is none. Every `poll` checks this."""
    return _engine


def SelectInProcessReceiver(selected: bool) -> None:
    """Say whether Blender itself hosts a painting receiver. Set before `register`."""
    global _inProcessReceiver
    _inProcessReceiver = selected


def InProcessReceiverSelected() -> bool:
    """Whether Blender hosts a painting receiver of its own."""
    return _inProcessReceiver


def _selectable(found: type) -> bool:
    """Whether this class may be registered given what the add-on is hosting."""
    return _inProcessReceiver or not getattr(found, "RequiresInProcessReceiver", False)


def _registrableBases() -> tuple[type, ...]:
    """The Blender base classes this build of Blender offers."""
    found = (getattr(bpy.types, name, None) for name in _REGISTRABLE_TYPE_NAMES)
    return tuple({base for base in found if isinstance(base, type)})


def _declaredClasses() -> list[type]:
    """Every class defined in this package, in a stable order.

    Modules are visited in alphabetical order, and within a module the classes come out in the order
    they are written. That matters when one class refers to another, such as a sub-panel naming its
    parent: write the parent first.
    """
    classes: list[type] = []
    for found in sorted(pkgutil.iter_modules(__path__), key=lambda entry: entry.name):
        module = importlib.import_module(f"{__name__}.{found.name}")
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
    return [found for found in _declaredClasses() if issubclass(found, bases) and _selectable(found)]


def RegisteredTools() -> list[type]:
    """The toolbar tools, which Blender adds through a different call than every other class."""
    base = getattr(bpy.types, "WorkSpaceTool", None)
    if base is None:
        return []
    return [found for found in _declaredClasses() if issubclass(found, base) and _selectable(found)]


def register() -> None:
    """Register everything in this package with Blender.

    Classes first, then tools: a tool names the operator it runs, so that operator has to exist.
    """
    for found in RegisteredClasses():
        bpy.utils.register_class(found)
        _registered.append(found)
    for tool in RegisteredTools():
        bpy.utils.register_tool(tool, separator=True, group=False)
        _registeredTools.append(tool)


def unregister() -> None:
    """Remove exactly what `register` added, in reverse."""
    while _registeredTools:
        bpy.utils.unregister_tool(_registeredTools.pop())
    while _registered:
        bpy.utils.unregister_class(_registered.pop())
