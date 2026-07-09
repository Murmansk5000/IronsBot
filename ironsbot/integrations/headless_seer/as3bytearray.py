# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: N802
import struct
from typing import Any, get_args

from typing_extensions import Self

from .type_hint import Buffer, EndianTypes


class AS3ByteArray(bytearray):
    # forked from https://github.com/wwqgtxx/lyp_pv/blob/master/lib/_b/_flash/byte_array.py
    __slots__ = ("_endian", "_pos")

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._endian: EndianTypes = "!"
        self._pos: int = 0  # position

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(hex={self}, length={len(self)})"

    def __str__(self) -> str:
        return self.hex(" ")

    def read_bytes(self, size: int = 0) -> bytes:
        if size < 0:
            raise ValueError("can not read bytes size", size)
        # read data to bytes and update pos
        try:
            out = bytes(self[self._pos : self._pos + size])
        except IndexError:
            raise IndexError("no enough data to read, bytes size", size) from None
        self._pos += size
        return out

    def write_bytes(self, data: Buffer) -> None:
        """
        write some raw bytes from current position, and increase position after write
        """
        # write data and update pos
        self[self._pos : self._pos + len(data)] = data
        self._pos += len(data)

    # base convert functions
    def _pack(self, mode: str, raw: Any) -> bytes:
        return struct.pack(self._endian + mode, raw)

    def _unpack(self, mode: str, raw: Any) -> tuple[Any, ...]:
        return struct.unpack(self._endian + mode, raw)

    def resize(self, new_size: int) -> None:
        extendsize = len(self) - new_size
        if extendsize > 0:
            self[:] = self[0:new_size]
        elif extendsize < 0:
            self.extend((0,) * abs(extendsize))

    @property
    def endian(self) -> EndianTypes:
        return self._endian

    @endian.setter
    def endian(self, value: EndianTypes) -> None:
        if value in get_args(EndianTypes):
            self._endian = value
        else:
            raise ValueError("no such endian", value)

    @property
    def position(self) -> int:
        return self._pos

    @position.setter
    def position(self, value: int) -> None:
        if value < 0:
            raise ValueError("can not set position to", value)
        self._pos = value

    @property
    def remaining(self) -> int:
        return len(self) - self._pos

    def clear(self) -> None:
        super().clear()
        self._pos = 0

    ## complex read and write functions

    # out :ByteArray, offset :uint, length :uint
    def readBytes(self, out: Self, offset: int = 0, length: int = 0) -> None:
        if length < 0:
            raise ValueError("can not read length", length)
        if length == 0:
            length = len(out) - offset

        # read data
        data = self.read_bytes(length)
        # write bytes to the ByteArray
        old = out.position  # NOTE save and restore old position
        out.position = offset
        out.write_bytes(data)
        out.position = old

    def writeBytes(self, raw: Self, offset: int = 0, length: int = 0) -> None:
        if length < 0:
            raise ValueError("can not write length", length)
        if length == 0:
            length = len(raw) - offset

        old = raw.position
        raw.position = offset
        data = raw.read_bytes(length)
        raw.position = old
        # write bytes to self
        self.write_bytes(data)

    def readUTFBytes(self, length: int) -> str:
        blob = self.read_bytes(length)
        return blob.decode("utf-8")

    def writeUTFBytes(self, value: str) -> None:
        blob = value.encode("utf-8")
        self.write_bytes(blob)

    def readMultiByte(self, length: int, charset: str) -> str:
        blob = self.read_bytes(length)
        # decode blob to text
        return blob.decode(charset)

    def writeMultiByte(self, value: str, charset: str) -> None:
        # encode text to binary
        blob = value.encode(charset)
        self.write_bytes(blob)

    def _read_value(self, mode: str, size: int) -> Any:
        raw = self.read_bytes(size)
        out = self._unpack(mode, raw)
        return out[0]

    def readBoolean(self) -> bool:
        return self._read_value("?", 1)

    def readByte(self) -> int:
        return self._read_value("b", 1)

    def readUnsignedByte(self) -> int:
        return self._read_value("B", 1)

    def readShort(self) -> int:
        return self._read_value("h", 2)

    def readUnsignedShort(self) -> int:
        return self._read_value("H", 2)

    def readInt(self) -> int:
        return self._read_value("i", 4)

    def readUnsignedInt(self) -> int:
        return self._read_value("I", 4)

    def readFloat(self) -> float:
        return self._read_value("f", 4)

    def readDouble(self) -> float:
        return self._read_value("d", 8)

    def _write_value(self, mode: str, raw: Any) -> None:
        data = self._pack(mode, raw)
        self.write_bytes(data)

    def writeBoolean(self, value: int) -> None:
        self._write_value("?", value)

    def writeByte(self, value: int) -> None:
        self._write_value("b", value)

    def writeUnsignedByte(self, value: int) -> None:
        self._write_value("B", value)

    def writeShort(self, value: int) -> None:
        self._write_value("h", value)

    def writeUnsignedShort(self, value: int) -> None:
        self._write_value("H", value)

    def writeInt(self, value: int) -> None:
        self._write_value("i", value)

    def writeUnsignedInt(self, value: int) -> None:
        self._write_value("I", value)

    def writeFloat(self, value: float) -> None:
        self._write_value("f", value)

    def writeDouble(self, value: float) -> None:
        self._write_value("d", value)
