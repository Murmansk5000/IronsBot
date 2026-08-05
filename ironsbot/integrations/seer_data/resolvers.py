# SPDX-License-Identifier: MIT
# ruff: noqa: TRY003
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from seerapi_models.build_model import BaseResModel
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SQLModelSession
from sqlmodel import col, func, select

from ironsbot.core.aliases import AliasMatch, AliasResolution
from ironsbot.services.seer.data import ALIAS_DB, SEERAPI_DB

from .normalization import IGNORED_CHARS as _IGNORED_CHARS
from .normalization import strip_special as _strip_special

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.seer.data import SessionMap

    from .orm import BaseAliasORM

_T_Model = TypeVar("_T_Model", bound=BaseResModel)
_T_Model_co = TypeVar("_T_Model_co", bound=BaseResModel, covariant=True)
logger = logging.getLogger(__name__)


def _col_strip_special(column: Any) -> Any:
    """构建一个 SQL 表达式，将列中的特殊字符逐个替换为空字符串。"""
    expr = column
    for char in _IGNORED_CHARS:
        expr = func.replace(expr, char, "")
    return expr


class Resolver(Protocol[_T_Model_co]):
    """从用户输入解析出匹配的模型对象。"""

    def __call__(self, sessions: SessionMap, arg: str) -> Iterable[_T_Model_co]: ...


class IdResolver(Generic[_T_Model]):
    """当输入为纯数字时，按主键 ID 获取单个对象。"""

    __slots__ = ("db_name", "model")

    def __init__(self, model: type[_T_Model], *, db_name: str = SEERAPI_DB) -> None:
        self.model = model
        self.db_name = db_name

    def __repr__(self) -> str:
        return (
            f"IdResolver(model={self.model.resource_name()!r}, "
            f"db_name={self.db_name!r})"
        )

    def __call__(self, sessions: SessionMap, arg: str) -> tuple[_T_Model] | tuple[()]:
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
        db_name: str = SEERAPI_DB,
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

    def __call__(self, sessions: SessionMap, arg: str) -> Iterable[_T_Model]:
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
        alias_db: str = ALIAS_DB,
        data_db: str = SEERAPI_DB,
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

    def alias_lookup(
        self,
        sessions: SessionMap,
    ) -> DatabaseAliasLookup[_T_Model]:
        """Bind this domain-owned lookup to the current data sessions."""

        return DatabaseAliasLookup(
            sessions,
            model=self.model,
            alias_model=self.alias_model,
            alias_db=self.alias_db,
            data_db=self.data_db,
        )

    def __call__(self, sessions: SessionMap, arg: str) -> Iterable[_T_Model]:
        return tuple(
            match.value
            for match in self.alias_lookup(sessions).resolve_alias(arg).matches
        )


class DatabaseAliasLookup(Generic[_T_Model]):
    """Session-bound AliasLookup implementation for a published alias table."""

    __slots__ = ("alias_db", "alias_model", "data_db", "model", "sessions")

    def __init__(
        self,
        sessions: SessionMap,
        *,
        model: type[_T_Model],
        alias_model: type[BaseAliasORM],
        alias_db: str,
        data_db: str,
    ) -> None:
        self.sessions = sessions
        self.model = model
        self.alias_model = alias_model
        self.alias_db = alias_db
        self.data_db = data_db

    def resolve_alias(self, reference: object) -> AliasResolution[_T_Model]:
        """Resolve one query while preserving entity-level ambiguity information."""

        text = str(reference).strip()
        if not text:
            return AliasResolution(reference=text)
        aliases = self._matching_aliases(text)
        if not aliases:
            return AliasResolution(reference=text)
        return AliasResolution(
            reference=text,
            matches=self._matching_models(aliases),
        )

    def _matching_aliases(self, text: str) -> tuple[BaseAliasORM, ...]:
        alias_session = self.sessions.get(self.alias_db)
        if alias_session is None:
            logger.warning("%r: 未找到别名数据库会话", self)
            return ()

        stripped_arg = _strip_special(text).casefold()
        if not stripped_arg:
            return ()
        try:
            statement = select(self.alias_model).where(
                func.lower(_col_strip_special(col(self.alias_model.name))).like(
                    f"%{stripped_arg}%"
                )
            )
            return tuple(alias_session.exec(statement).all())
        except OperationalError:
            logger.exception("DatabaseAliasLookup failed")
            return ()

    def _matching_models(
        self,
        aliases: tuple[BaseAliasORM, ...],
    ) -> tuple[AliasMatch[_T_Model], ...]:
        data_session = self.sessions.get(self.data_db)
        if data_session is None:
            logger.warning("%r: 未找到数据数据库会话", self)
            return ()

        values_by_id = {
            value.id: value
            for value in data_session.exec(
                select(self.model).where(
                    col(self.model.id).in_({alias.target_id for alias in aliases})
                )
            ).all()
        }
        matches: list[AliasMatch[_T_Model]] = []
        seen_ids: set[int] = set()
        for alias in aliases:
            if alias.target_id in seen_ids:
                continue
            value = values_by_id.get(alias.target_id)
            if value is not None:
                seen_ids.add(alias.target_id)
                matches.append(AliasMatch(alias.name, value))
        return tuple(matches)


class Getter(Generic[_T_Model]):
    __slots__ = ("model", "resolvers")

    def __init__(self, model: type[_T_Model], *resolvers: Resolver[_T_Model]) -> None:
        self.model = model
        self.resolvers = resolvers

    def get(self, session: SQLModelSession, id_: int) -> _T_Model | None:
        return session.get(self.model, id_)

    def __call__(
        self,
        sessions: SessionMap,
        arg: str,
    ) -> tuple[_T_Model, ...]:
        if not arg:
            return ()

        seen: dict[int, _T_Model] = {}
        for resolver in self.resolvers:
            for obj in resolver(sessions, arg):
                seen.setdefault(obj.id, obj)

        return tuple(seen.values())
