"""Finds the interface wrappers in this package, so nothing has to keep a list of them.

This is the Python counterpart of `private/interface_registry.cpp` on the C side: the one place that
knows which interfaces exist. The difference is that this one does not need editing. It looks for
every `Interface` subclass in `abi/interfaces/`, so adding an interface means adding a module there
and nothing else.
"""

from __future__ import annotations

import importlib
import pkgutil

from .interfaces import Interface


def InterfaceTypes() -> list[type[Interface]]:
    """Every interface wrapper in `abi/interfaces/`, ordered by module name so startup is repeatable.

    A class is only picked up if it is defined in the module it is found in, so importing an
    interface into another module cannot make the engine create it twice.
    """
    found: list[type[Interface]] = []
    # `__path__` belongs to the package, not to a module inside it. By the time anything calls this,
    # the package is fully imported, so asking for it here is safe.
    package = importlib.import_module(f"{__package__}.interfaces")
    for module in sorted(entry.name for entry in pkgutil.iter_modules(package.__path__)):
        loaded = importlib.import_module(f"{package.__name__}.{module}")
        found += [
            value
            for value in vars(loaded).values()
            if isinstance(value, type)
            and issubclass(value, Interface)
            and value is not Interface
            and value.__module__ == loaded.__name__
        ]
    return found
