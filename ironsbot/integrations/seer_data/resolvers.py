# SPDX-License-Identifier: MIT
# ruff: noqa: TRY003
from collections.abc import Iterable
from typing import Any, Generic, Protocol, TypeVar

from nonebot import logger
from nonebot.params import Depends
from seerapi_models.build_model import BaseResModel
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SQLModelSession
from sqlmodel import col, func, select

from ironsbot.utils.parse_arg import parse_string_arg

from .normalization import IGNORED_CHARS as _IGNORED_CHARS
from .normalization import strip_special as _strip_special
from .orm import BaseAliasORM
from .sessions import _ALIAS_DB, _SEERAPI_DB, AllSessions

_T_Model = TypeVar("_T_Model", bound=BaseResModel)
_T_Model_co = TypeVar("_T_Model_co", bound=BaseResModel, covariant=True)


def _col_strip_special(column: Any) -> Any:
    """构建一个 SQL 表达式，将列中的特殊字符逐个替换为空字符串。"""
    expr = column
    for char in _IGNORED_CHARS:
        expr = func.replace(expr, char, "")
    return expr


class Resolver(Protocol[_T_Model_co]):
    """从用户输入解析出匹配的模型对象。"""

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[_T_Model_co]: ...


class IdResolver(Generic[_T_Model]):
    """当输入为纯数字时，按主键 ID 获取单个对象。"""

    __slots__ = ("db_name", "model")

    def __init__(self, model: type[_T_Model], *, db_name: str = _SEERAPI_DB) -> None:
        self.model = model
        self.db_name = db_name

    def __repr__(self) -> str:
        return (
            f"IdResolver(model={self.model.resource_name()!r}, "
            f"db_name={self.db_name!r})"
        )

    def __call__(self, sessions: AllSessions, arg: str) -> tuple[_T_Model] | tuple[()]:
        if not arg.isdigit():
            return ()
        session = sessions.get(self.db_name)
        if session is None:
            logger.warning(f"{self!r}: 未找到数据库会话")
            return ()
        obj = session.get(self.model, int(arg))
        return (obj,) if obj else ()


class NameResolver(Generic[_T_Model]):
    """按名称列模糊搜索，直接返回完整模型对象。"""

    __slots__ = ("db_name", "model", "name_column")

    def __init__(
        self,
        model: type[_T_Model],
        *,
        db_name: str = _SEERAPI_DB,
        name_column: str = "name",
    ) -> None:
        if not hasattr(model, name_column):
            raise ValueError(
                f"Model {model.resource_name()} has no {name_column} column"
            )
        self.db_name = db_name
        self.model = model
        self.name_column = getattr(model, name_column)

    def __repr__(self) -> str:
        return (
            "NameResolver("
            f"model={self.model.resource_name()!r}, "
            f"db_name={self.db_name!r}, "
            f"name_column={self.name_column!r}"
            ")"
        )

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[_T_Model]:
        session = sessions.get(self.db_name)
        if session is None:
            logger.warning(f"{self!r}: 未找到数据库会话")
            return ()

        stripped_arg = _strip_special(arg)
        statement = select(self.model).where(
            _col_strip_special(col(self.name_column)).like(f"%{stripped_arg}%")
        )
        return session.exec(statement).all()


class AliasResolver(Generic[_T_Model]):
    """通过别名表搜索 ID，再从主数据库获取完整对象。"""

    __slots__ = ("alias_db", "alias_model", "data_db", "model")

    def __init__(
        self,
        model: type[_T_Model],
        alias_model: type[BaseAliasORM],
        *,
        alias_db: str = _ALIAS_DB,
        data_db: str = _SEERAPI_DB,
    ) -> None:
        self.model = model
        self.alias_model = alias_model
        self.alias_db = alias_db
        self.data_db = data_db

    def __repr__(self) -> str:
        return (
            "AliasResolver("
            f"model={self.model.resource_name()!r}, "
            f"alias_model={self.alias_model.__name__!r}, "
            f"alias_db={self.alias_db!r}, "
            f"data_db={self.data_db!r}"
            ")"
        )

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[_T_Model]:
        alias_session = sessions.get(self.alias_db)
        if alias_session is None:
            logger.warning(f"{self!r}: 未找到别名数据库会话")
            return ()

        try:
            stripped_arg = _strip_special(arg.strip()).casefold()
            statement = select(self.alias_model).where(
                func.lower(_col_strip_special(col(self.alias_model.name))).like(
                    f"%{stripped_arg}%"
                )
            )
            aliases = alias_session.exec(statement).all()
            ids = {alias.target_id for alias in aliases}
        except OperationalError as e:
            logger.error(f"AliasResolver error: {e}")
            return ()

        if not ids:
            return ()

        data_session = sessions.get(self.data_db)
        if data_session is None:
            logger.warning(f"{self!r}: 未找到数据数据库会话")
            return ()

        return data_session.exec(
            select(self.model).where(col(self.model.id).in_(ids))
        ).all()


class Getter(Generic[_T_Model]):
    __slots__ = ("model", "resolvers")

    def __init__(self, model: type[_T_Model], *resolvers: Resolver[_T_Model]) -> None:
        self.model = model
        self.resolvers = resolvers

    def get(self, session: SQLModelSession, id_: int) -> _T_Model | None:
        return session.get(self.model, id_)

    def __call__(
        self, sessions: AllSessions, arg: str = Depends(parse_string_arg)
    ) -> tuple[_T_Model, ...]:
        if not arg:
            return ()

        seen: dict[int, _T_Model] = {}
        for resolver in self.resolvers:
            for obj in resolver(sessions, arg):
                seen.setdefault(obj.id, obj)

        return tuple(seen.values())

    def __or__(self, other: "Getter[_T_Model]") -> "Getter[_T_Model]":
        if not isinstance(other, Getter):
            raise TypeError(f"Cannot combine Getter with {type(other)}")
        return Getter(self.model, *self.resolvers, *other.resolvers)


def from_id_get_name(
    getter: Getter[_T_Model],
    _id: int,
    *,
    sessions: AllSessions,
) -> str:
    if not (objs := getter(sessions, str(_id))):
        return ""

    obj = objs[0]
    if (name := getattr(obj, "name", None)) is None:
        raise ValueError(f"Model {getter.model.resource_name()} has no name attribute")

    return name
