# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Protocol, runtime_checkable


@runtime_checkable
class StringCodec(Protocol):
    """字符串编解码处理协议，Unicode 字段类型的第二个参数须实现此协议。"""

    @classmethod
    def encode(cls, value: str) -> bytes:
        """将字符串编码为字节序列。"""
        ...

    @classmethod
    def decode(cls, value: bytes) -> str:
        """将字节序列解码为字符串。"""
        ...


class UTF8Codec:
    """使用 UTF-8 编码的字符串处理类。"""

    @classmethod
    def encode(cls, value: str) -> bytes:
        return value.encode("utf-8")

    @classmethod
    def decode(cls, value: bytes) -> str:
        return value.decode("utf-8", errors="ignore").strip("\x00")


class GBKCodec:
    """使用 GBK 编码的字符串处理类。"""

    @classmethod
    def encode(cls, value: str) -> bytes:
        return value.encode("gbk")

    @classmethod
    def decode(cls, value: bytes) -> str:
        return value.decode("gbk").strip("\x00")
