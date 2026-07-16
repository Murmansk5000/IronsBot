# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Hashable, Sequence
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    TypeAlias,
    TypeVar,
    get_args,
    get_origin,
)

from typing_extensions import Protocol, TypeIs, TypeVarTuple, Unpack

T_Sequence = TypeVar("T_Sequence", bound=Sequence)

Buffer: TypeAlias = bytearray | bytes | memoryview
T_Buffer_co = TypeVar("T_Buffer_co", bound=Buffer, covariant=True)

EndianTypes: TypeAlias = Literal["@", "=", "<", ">", "!"]

T_Deserializable = TypeVar("T_Deserializable")

SocketRecvPacketBody: TypeAlias = Any


class CommandID(int, Generic[T_Deserializable]): ...


T_Key = TypeVar("T_Key", bound=Hashable)
T_Args = TypeVarTuple("T_Args")


class Listener(Protocol[Unpack[T_Args]]):
    def __call__(self, *args: Unpack[T_Args]) -> None: ...


def is_literal_type(type_: type[Any]) -> bool:
    return get_origin(type_) is Literal


def literal_values(type_: type[Any]) -> tuple[Any, ...]:
    return get_args(type_)


def all_literal_values(type_: type[Any]) -> tuple[Any, ...]:
    """
    This method is used to retri
    。eve all Literal values as
    Literal can be used recursively (see https://www.python.org/dev/peps/pep-0586)
    e.g. `Literal[Literal[Literal[1, 2, 3], "foo"], 5, None]`
    """
    if not is_literal_type(type_):
        return (type_,)

    values = literal_values(type_)
    return tuple(x for value in values for x in all_literal_values(value))


def is_annotated(type_: Any) -> bool:
    return get_origin(type_) is Annotated


def flatten_annotated(type_: Annotated) -> tuple[Any, ...]:
    if not is_annotated(type_):
        return (type_,)
    return tuple(j for i in get_args(type_) for j in flatten_annotated(i))


_CT = TypeVar("_CT")


def safe_issubclass(type_: Any, *cls: type[_CT]) -> TypeIs[type[_CT]]:
    try:
        return issubclass(type_, cls)
    except TypeError:
        return False
