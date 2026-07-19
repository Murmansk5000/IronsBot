# SPDX-License-Identifier: GPL-3.0-or-later
import struct


class BufferReader:
    __slots__ = ("_data", "_offset")

    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._data = memoryview(data)
        self._offset = 0

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def remaining(self) -> int:
        return max(0, len(self._data) - self._offset)

    def has_remaining(self, size: int = 1) -> bool:
        return self._offset + size <= len(self._data)

    def read_uint32(self) -> int:
        return self._read("!I", 4)

    def read_int32(self) -> int:
        return self._read("!i", 4)

    def read_uint16(self) -> int:
        return self._read("!H", 2)

    def read_uint8(self) -> int:
        return self._read("!B", 1)

    def read_string(self, length: int) -> str:
        self._ensure(length)
        raw = self._data[self._offset : self._offset + length].tobytes()
        self._offset += length
        return raw.decode("utf-8", errors="ignore").replace("\x00", "")

    def skip(self, size: int) -> None:
        self._ensure(size)
        self._offset += size

    def _read(self, fmt: str, size: int) -> int:
        self._ensure(size)
        value = struct.unpack_from(fmt, self._data, self._offset)[0]
        self._offset += size
        return int(value)

    def _ensure(self, size: int) -> None:
        if not self.has_remaining(size):
            raise ValueError(  # noqa: TRY003
                "buffer underflow: "
                f"need {size} bytes, remaining {self.remaining}, offset {self._offset}"
            )
