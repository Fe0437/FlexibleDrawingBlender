"""Decode the self-describing values the engine hands out, by the names they carry.

The engine encodes plain C++ records, reading their field names and enumerator names while it
compiles (src/host/abi/private/reflected_encoding.h). This module is the other half: it knows the
format and nothing about what the values mean, so a field the engine adds arrives here with no edit.
The format is specified in src/host/abi/README.md, under "Self-describing values".

| Encoded    | Decoded                                          |
| ---------- | ------------------------------------------------ |
| absent     | `None`                                           |
| boolean    | `bool`                                           |
| integer    | `int`                                            |
| real       | `float`                                          |
| text       | `str`                                            |
| enumerator | `str`: the C++ enumerator's name, such as "Choice" |
| list       | `tuple`                                          |
| record     | `Record`, whose attributes are the C++ field names |
"""

from __future__ import annotations

import struct
from typing import Any

#: The marker every encoding starts with, and the only format version this decoder reads.
MARKER = b"FDRE"
FORMAT_VERSION = 1


class Record:
    """One decoded C++ record: read-only attributes named as the C++ fields are."""

    __slots__ = ("_fields",)

    def __init__(self, fields: dict[str, Any]) -> None:
        object.__setattr__(self, "_fields", fields)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a decoded record is read-only")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Record) and self._fields == other._fields

    def __hash__(self) -> int:
        return hash(tuple(self._fields.items()))

    def __repr__(self) -> str:
        return f"Record({', '.join(f'{name}={value!r}' for name, value in self._fields.items())})"


class ValueReader:
    """Reads the format front to back; any malformed byte raises ValueError."""

    def __init__(self, data: bytes) -> None:
        self._data = memoryview(data)
        self._position = 0

    def _take(self, count: int) -> memoryview:
        if self._position + count > len(self._data):
            raise ValueError("self-describing value ends early")
        taken = self._data[self._position : self._position + count]
        self._position += count
        return taken

    def _unpack(self, layout: str) -> Any:
        return struct.unpack(layout, self._take(struct.calcsize(layout)))[0]

    def _text(self) -> str:
        return bytes(self._take(self._unpack("<I"))).decode("utf-8")

    def Value(self) -> Any:
        """Read the next value, whatever its shape."""
        tag = self._unpack("<B")
        if tag == 0:
            return None
        if tag == 1:
            return self._unpack("<B") != 0
        if tag == 2:
            return self._unpack("<q")
        if tag == 3:
            return self._unpack("<Q")
        if tag == 4:
            return self._unpack("<d")
        if tag in (5, 6):
            return self._text()
        if tag == 7:
            return tuple(self.Value() for _ in range(self._unpack("<I")))
        if tag == 8:
            fields: dict[str, Any] = {}
            for _ in range(self._unpack("<I")):
                name = self._text()
                fields[name] = self.Value()
            return Record(fields)
        raise ValueError(f"self-describing value has an unknown tag {tag}")

    def End(self) -> None:
        """Refuse bytes left after the value."""
        if self._position != len(self._data):
            raise ValueError("self-describing value has trailing bytes")


def Decode(data: bytes) -> Any:
    """Decode one value the engine encoded; raises ValueError for any other bytes."""
    reader = ValueReader(data)
    if bytes(reader._take(len(MARKER))) != MARKER:
        raise ValueError("not a self-describing value")
    version = reader._unpack("<I")
    if version != FORMAT_VERSION:
        raise ValueError(f"self-describing format {version} is not {FORMAT_VERSION}")
    value = reader.Value()
    reader.End()
    return value
