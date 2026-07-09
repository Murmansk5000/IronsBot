# SPDX-License-Identifier: GPL-3.0-or-later
import dataclasses
import struct
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from typing_extensions import Self, dataclass_transform

from ..type_hint import Buffer, flatten_annotated, safe_issubclass
from .fields import is_binary

if TYPE_CHECKING:
    from .fields import BinaryTag, SizeGetter


_validated_classes: set[type] = set()


@dataclass_transform()
@dataclass(slots=True)
class Serializable:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        set_slots = "__slots__" not in cls.__dict__
        dataclass(slots=set_slots)(cls)

    def pack(self) -> bytes:
        return struct.pack(self.calc_struct_format(), *self._get_flat_values())

    def pack_into(self, buffer: Buffer, offset: int = 0) -> None:
        struct.pack_into(
            self.calc_struct_format(), buffer, offset, *self._get_flat_values()
        )

    @staticmethod
    def _resolve_tag(field: dataclasses.Field) -> type["BinaryTag | Serializable"]:
        if isinstance(field.type, str):
            raise TypeError("标注字段的属性类型提示不能为向前引用", field.name)
        return (None, *flatten_annotated(field.type))[-1]

    @classmethod
    def _validate_fields(cls) -> None:
        if cls in _validated_classes:
            return
        fields = dataclasses.fields(cls)
        rest_field: str | None = None
        for field in fields:
            if rest_field is not None:
                raise TypeError(
                    f"rest 标签字段 '{rest_field}' 必须位于最后，"
                    f"但其后还有字段 '{field.name}'"
                )
            tag = Serializable._resolve_tag(field)
            if is_binary(tag) and getattr(tag, "rest", False):
                rest_field = field.name
        _validated_classes.add(cls)

    @staticmethod
    def _resolve_elem_tag(elem_cls: Any) -> Any:
        return (None, *flatten_annotated(elem_cls))[-1]

    def calc_struct_format(self, endian: str = "!") -> str:
        """计算 struct 格式字符串。

        遍历所有字段的类型注解，将 Binary 标签的 format_str 按
        length 组合为完整的格式字符串。Array 字段递归展开元素类型
        的格式，嵌套 Serializable 字段递归展开。
        """
        self._validate_fields()
        fmt_parts: list[str] = []
        for field in dataclasses.fields(self):
            tag = self._resolve_tag(field)

            if is_binary(tag):
                length = 1
                size_func = getattr(tag, "size_func", None)
                rest = getattr(tag, "rest", False)
                if size_func is not None:
                    length = cast("SizeGetter", size_func)(self)

                elem_cls = getattr(tag, "element_type", None)
                if elem_cls is not None:
                    elem_tag = self._resolve_elem_tag(elem_cls)
                    if safe_issubclass(elem_tag, Serializable):
                        items: list[Serializable] = getattr(self, field.name)
                        if rest:
                            length = len(items)
                        if items:
                            elem_fmt = items[0].calc_struct_format(endian="")
                            fmt_parts.append(elem_fmt * length)
                    elif is_binary(elem_tag):
                        if rest:
                            length = len(getattr(self, field.name))
                        if length > 0:
                            fmt_parts.append(f"{length}{elem_tag.format_str}")
                elif rest:
                    obj = getattr(self, field.name)
                    pre = getattr(tag, "pre_processor", None)
                    if pre is not None:
                        obj = pre(self, obj)
                    length = len(obj)
                    fmt_parts.append(f"{length}{tag.format_str}")
                elif length > 1:
                    fmt_parts.append(f"{length}{tag.format_str}")
                else:
                    fmt_parts.append(tag.format_str)
            elif safe_issubclass(tag, Serializable):
                obj = getattr(self, field.name)
                fmt_parts.append(obj.calc_struct_format(endian=""))
            else:
                raise TypeError("不支持的类型", tag)

        return endian + "".join(fmt_parts)

    def _get_flat_values(self) -> list[Any]:
        """提取所有字段的值，展平嵌套 Serializable 和 Array。"""
        values: list[Any] = []
        for field in dataclasses.fields(self):
            tag = self._resolve_tag(field)
            obj = getattr(self, field.name)

            if is_binary(tag):
                elem_cls = getattr(tag, "element_type", None)
                if elem_cls is not None:
                    elem_tag = self._resolve_elem_tag(elem_cls)
                    if safe_issubclass(elem_tag, Serializable):
                        for item in obj:
                            values.extend(item._get_flat_values())
                    else:
                        pre = getattr(elem_tag, "pre_processor", None)
                        for item in obj:
                            values.append(pre(self, item) if pre is not None else item)
                else:
                    pre = getattr(tag, "pre_processor", None)
                    if pre is not None:
                        obj = pre(self, obj)
                    values.append(obj)
            elif safe_issubclass(tag, Serializable):
                values.extend(obj._get_flat_values())
            else:
                raise TypeError("不支持的类型", tag)

        return values


class Deserializable(Serializable):
    @classmethod
    def unpack(cls, data: Buffer, endian: str = "!") -> Self:
        mv = memoryview(data) if not isinstance(data, memoryview) else data
        instance, _ = cls._from_memoryview(mv, endian)
        return instance

    @classmethod
    def _from_memoryview(cls, mv: memoryview, endian: str) -> tuple[Self, memoryview]:
        cls._validate_fields()
        partial = SimpleNamespace()

        for field in dataclasses.fields(cls):
            tag = Serializable._resolve_tag(field)

            if is_binary(tag):
                length = 1
                size_func = getattr(tag, "size_func", None)
                rest = getattr(tag, "rest", False)
                if size_func is not None:
                    length = cast("SizeGetter", size_func)(partial)

                elem_cls = getattr(tag, "element_type", None)
                if elem_cls is not None:
                    elem_tag = Serializable._resolve_elem_tag(elem_cls)
                    if safe_issubclass(elem_tag, Deserializable):
                        items = []
                        if rest:
                            while len(mv) > 0:
                                item, mv = elem_tag._from_memoryview(mv, endian)
                                items.append(item)
                        else:
                            for _ in range(length):
                                item, mv = elem_tag._from_memoryview(mv, endian)
                                items.append(item)
                        setattr(partial, field.name, items)
                    elif is_binary(elem_tag):
                        if rest:
                            elem_size = struct.calcsize(endian + elem_tag.format_str)
                            length = len(mv) // elem_size
                        if length > 0:
                            fmt = f"{length}{elem_tag.format_str}"
                            full_fmt = endian + fmt
                            size = struct.calcsize(full_fmt)
                            unpacked = struct.unpack_from(full_fmt, mv)
                            mv = mv[size:]
                            post = getattr(elem_tag, "post_processor", None)
                            if post is not None:
                                unpacked = tuple(post(partial, v) for v in unpacked)
                            setattr(partial, field.name, unpacked)
                        else:
                            setattr(partial, field.name, ())
                else:
                    if rest:
                        length = len(mv)
                    fmt = tag.format_str if length == 1 else f"{length}{tag.format_str}"
                    full_fmt = endian + fmt
                    size = struct.calcsize(full_fmt)
                    (value,) = struct.unpack_from(full_fmt, mv)
                    mv = mv[size:]
                    post = getattr(tag, "post_processor", None)
                    if post is not None:
                        value = post(partial, value)
                    setattr(partial, field.name, value)

            elif safe_issubclass(tag, Deserializable):
                deser_cls = tag
                child, mv = deser_cls._from_memoryview(mv, endian)
                setattr(partial, field.name, child)
            else:
                raise TypeError("不支持的类型", tag)

        return cls(**vars(partial)), mv
