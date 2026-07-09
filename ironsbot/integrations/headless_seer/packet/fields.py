# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Callable
from types import EllipsisType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Protocol,
    cast,
    overload,
)

from typing_extensions import TypeIs

if TYPE_CHECKING:
    from .packet import Serializable

from operator import attrgetter as _attrgetter

from .codecs import StringCodec, UTF8Codec

SizeGetter = Callable[[Any], int]
SizeTypes = int | SizeGetter

PreProcessor = Callable[["Serializable", Any], Any]
PostProcessor = Callable[["Serializable", Any], Any]


def _wrap_size_func(count: SizeTypes) -> SizeGetter:
    return (lambda _: count) if isinstance(count, int) else count


@overload
def _create_wrapper(
    *,
    cls_name: str,
    cls_bases: tuple[type, ...],
    struct_mode: str,
    element_type: type | None = None,
    pre_processor: PreProcessor | None = None,
    post_processor: PostProcessor | None = None,
) -> "type[BinaryTag]": ...
@overload
def _create_wrapper(
    count: SizeTypes | EllipsisType,
    *,
    cls_name: str,
    cls_bases: tuple[type, ...],
    struct_mode: str,
    pre_processor: PreProcessor | None = None,
    post_processor: PostProcessor | None = None,
) -> "type[SequenceTag]": ...
@overload
def _create_wrapper(
    count: SizeTypes | EllipsisType,
    *,
    cls_name: str,
    cls_bases: tuple[type, ...],
    struct_mode: str,
    element_type: type | None,
    pre_processor: PreProcessor | None = None,
    post_processor: PostProcessor | None = None,
) -> "type[Array]": ...
def _create_wrapper(
    count: SizeTypes | EllipsisType | None = None,
    *,
    cls_name: str,
    cls_bases: tuple[type, ...],
    struct_mode: str,
    element_type: type | None = None,
    pre_processor: PreProcessor | None = None,
    post_processor: PostProcessor | None = None,
) -> "type[BinaryTag | SequenceTag | Array]":
    _d: dict[str, Any] = {
        "format_str": struct_mode,
        "__slots__": (),
    }
    if count is Ellipsis:
        _d["rest"] = True
    elif count is not None:
        _d["size_func"] = _wrap_size_func(cast("SizeTypes", count))
    if element_type is not None:
        _d["element_type"] = element_type
    if pre_processor is not None:
        _d["pre_processor"] = pre_processor
    if post_processor is not None:
        _d["post_processor"] = post_processor

    return type(cls_name, cls_bases, _d)  # type: ignore[type-arg]


class BinaryTag(Protocol):
    pre_processor: ClassVar[PreProcessor | None]
    post_processor: ClassVar[PostProcessor | None]
    format_str: ClassVar[str]


class SequenceTag(BinaryTag):
    size_func: ClassVar[SizeGetter]


class Array(SequenceTag):
    element_type: ClassVar[type["Serializable"] | None]

    def __class_getitem__(cls, params: tuple) -> type["Array"]:
        if not isinstance(params, tuple):
            params = (params,)

        if len(params) < 2:
            raise TypeError("Array 的参数不能为空")

        arg: Any = params[0]
        type_: type[Serializable] = params[1]

        if arg is Ellipsis:
            return _create_wrapper(  # type: ignore[return-value]
                ...,
                cls_name=f"_{type_.__name__}_{cls.__name__}",
                cls_bases=(),
                struct_mode="",
                element_type=type_,
            )

        if not (isinstance(arg, int) and arg >= 0) and not callable(arg):
            raise TypeError(
                "Array 的第一个参数必须为一个非负整数、可调用对象或 Ellipsis"
            )

        return _create_wrapper(
            cast("SizeTypes", arg),
            cls_name=f"_{type_.__name__}_{cls.__name__}",
            cls_bases=(),
            struct_mode="",
            element_type=type_,
        )


class Char(bytes, SequenceTag):
    __slots__ = ()

    def __class_getitem__(cls, params: tuple) -> type[SequenceTag]:
        if not isinstance(params, tuple):
            params = (params,)

        if len(params) != 1:
            raise TypeError("Char 的参数数量必须为一个")

        arg: Any = params[0]

        if arg is Ellipsis:
            return _create_wrapper(
                ...,
                cls_name=f"_{cls.__name__}",
                cls_bases=(bytes,),
                struct_mode="s",
            )

        if not (isinstance(arg, int) and arg >= 0) and not callable(arg):
            raise TypeError("Char 的参数必须为一个非负整数、可调用对象或 Ellipsis")

        return _create_wrapper(
            cast("SizeTypes", arg),
            cls_name=f"_{cls.__name__}",
            cls_bases=(bytes,),
            struct_mode="s",
        )


class Unicode(str, SequenceTag):
    __slots__ = ()

    def __class_getitem__(cls, params: tuple) -> type[SequenceTag | BinaryTag]:
        if not isinstance(params, tuple):
            params = (params,)

        if not (1 <= len(params) <= 2):
            raise TypeError("Unicode 的参数数量必须为 1 或 2 个")

        arg: Any = params[0]
        codec: type[StringCodec] = params[1] if len(params) > 1 else UTF8Codec

        if not isinstance(codec, type) or not issubclass(codec, StringCodec):
            raise TypeError(
                "Unicode 的第二个参数必须是实现了 StringCodec 协议的类"
            )

        if arg is Ellipsis:
            return _create_wrapper(
                ...,
                cls_name=f"_{cls.__name__}",
                cls_bases=(str,),
                struct_mode="s",
                pre_processor=lambda _, v: codec.encode(v),
                post_processor=lambda _, v: codec.decode(v),
            )

        if not (isinstance(arg, int) and arg >= 0) and not callable(arg):
            raise TypeError(
                "Unicode 的第一个参数必须为一个非负整数、可调用对象或 Ellipsis"
            )
        return _create_wrapper(
            cast("SizeTypes", arg),
            cls_name=f"_{cls.__name__}",
            cls_bases=(str,),
            struct_mode="s",
            pre_processor=lambda _, v: codec.encode(v),
            post_processor=lambda _, v: codec.decode(v),
        )


class BooleanType(BinaryTag):
    format_str: ClassVar[str] = "?"


class Byte(int, BinaryTag):
    format_str: ClassVar[str] = "b"


class UByte(int, BinaryTag):
    format_str: ClassVar[str] = "B"


class ShortType(int, BinaryTag):
    format_str: ClassVar[str] = "h"


class UShortType(int, BinaryTag):
    format_str: ClassVar[str] = "H"


class IntType(int, BinaryTag):
    format_str: ClassVar[str] = "i"


class UIntType(int, BinaryTag):
    format_str: ClassVar[str] = "I"


class FloatType(float, BinaryTag):
    format_str: ClassVar[str] = "f"


class DoubleType(float, BinaryTag):
    format_str: ClassVar[str] = "d"


Boolean = Annotated[bool, BooleanType]
Short = Annotated[int, ShortType]
UShort = Annotated[int, UShortType]
Int = Annotated[int, IntType]
UInt = Annotated[int, UIntType]
Float = Annotated[float, FloatType]
Double = Annotated[float, DoubleType]


def is_binary(type_: Any) -> TypeIs[type[BinaryTag]]:
    return hasattr(type_, "format_str")


def attrgetter(*attrs: str) -> Callable[[Any], tuple[Any, ...]]:
    """
    返回一个无论输入有几个属性，始终返回元组类型的attrgetter
    """
    base_getter = _attrgetter(*attrs)
    if not attrs:
        return lambda _: ()
    if len(attrs) == 1:
        return lambda obj: (base_getter(obj),)
    return lambda obj: tuple(base_getter(obj))


def size_by(attr: str) -> SizeGetter:
    return lambda obj: attrgetter(attr)(obj)[0]
