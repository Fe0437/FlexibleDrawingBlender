"""flexible_drawing_ui_schema.h in Python. Generated: do not edit — see this package's __init__.

The ui_schema interface: its table, its records, its constants, and its host values.
"""

from __future__ import annotations

import ctypes

from .bootstrap import fd_engine, fd_engine_status


# Status codes
# Zero is success. The bootstrap owns 0-999; each interface owns a block from 1000 up.
FD_UI_SCHEMA_STATUS_UNRESOLVED = 1200


# Interfaces
# Names and generations for fd_engine_get_interface.
FD_INTERFACE_UI_SCHEMA = "ui_schema"
FD_INTERFACE_UI_SCHEMA_VERSION = 2


class fd_ui_schema_api(ctypes.Structure):
    """Engine-owned table; struct_size reports how many entry points it populated."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        (
            "describe",
            ctypes.CFUNCTYPE(
                fd_engine_status, fd_engine, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
                ctypes.POINTER(ctypes.c_uint64)
            ),
        ),
    ]
