"""flexible_drawing_bootstrap.h in Python. Generated: do not edit — see this package's __init__.

The handshake every host performs first. This never changes.
"""

from __future__ import annotations

import ctypes


# The ABI this mirror was rendered from. fd_engine_create refuses anything it cannot serve.
FD_ABI_VERSION_MAJOR = 0
FD_ABI_VERSION_MINOR = 0
FD_ABI_VERSION = (FD_ABI_VERSION_MAJOR << 16) | FD_ABI_VERSION_MINOR


def FD_ABI_VERSION_MAJOR_OF(version: int) -> int:
    """Extract the major component, which caller and engine must agree on exactly."""
    return version >> 16


def FD_ABI_VERSION_MINOR_OF(version: int) -> int:
    """Extract the minor component, which is negotiated down to what both sides serve."""
    return version & 0xFFFF


# Status codes
# Zero is success. The bootstrap owns 0-999; each interface owns a block from 1000 up.
FD_ENGINE_STATUS_INCOMPATIBLE_ABI = 3
FD_ENGINE_STATUS_INVALID_ARGUMENT = 4
FD_ENGINE_STATUS_OK = 0
FD_ENGINE_STATUS_UNKNOWN_INTERFACE = 5


# Constants
# Every other value the header pins, which a host compares against by number.
FD_LOG_SEVERITY_DEBUG = 1
FD_LOG_SEVERITY_ERROR = 4
FD_LOG_SEVERITY_INFO = 2
FD_LOG_SEVERITY_TRACE = 0
FD_LOG_SEVERITY_WARNING = 3


# Every fallible boundary call returns this; it is an unsigned code, never an errno.
fd_engine_status = ctypes.c_uint32
# An engine instance. Opaque by contract: ctypes must carry the address and never read it.
fd_engine = ctypes.c_void_p


fd_log_callback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p)


class fd_host_api(ctypes.Structure):
    """Sized record: struct_size is stamped on construction, so it can never be omitted."""

    _fields_ = [
        ("struct_size", ctypes.c_uint64),
        ("user_data", ctypes.c_void_p),
        ("log", fd_log_callback),
    ]

    def __init__(self, *arguments: object, **keywords: object) -> None:
        super().__init__(ctypes.sizeof(type(self)), *arguments, **keywords)


# The frozen exported surface, as (restype, argtypes). A loader applies every entry, so an
# unprototyped call — which ctypes would silently marshal as int — cannot happen.
BOOTSTRAP_PROTOTYPES = {
    "fd_engine_abi_version": (ctypes.c_uint32, []),
    "fd_engine_create": (
        fd_engine_status,
        [ctypes.c_uint32, ctypes.POINTER(fd_host_api), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(fd_engine)]
    ),
    "fd_engine_destroy": (None, [fd_engine]),
    "fd_engine_get_interface": (
        fd_engine_status,
        [fd_engine, ctypes.c_char_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    ),
    "fd_engine_last_error": (ctypes.c_char_p, [fd_engine]),
    "fd_engine_round_trip": (ctypes.c_uint64, [ctypes.c_uint64]),
    "fd_engine_version_string": (ctypes.c_char_p, []),
}
