# SPDX-License-Identifier: GPL-3.0-or-later
import struct
from typing import Any

from .type_hint import Buffer


class AS3ByteArray(bytearray):
    # forked from https://github.com/wwqgtxx/lyp_pv/blob/master/lib/_b/_flash/byte_array.py
    __slots__ = ("_pos",)

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._pos = 0

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(hex={self}, length={len(self)})"

    def __str__(self) -> str:
        return self.hex(" ")

    def write_bytes(self, data: Buffer) -> None:
        self[self._pos : self._pos + len(data)] = data
        self._pos += len(data)

    def write_uint32(self, value: int) -> None:
        self.write_bytes(struct.pack("!I", value))
