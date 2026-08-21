# SPDX-License-Identifier: MIT
# ruff: noqa: N802

import re
from collections.abc import AsyncGenerator, Callable, Iterable
from typing import Annotated, Any, Generic, Protocol, TypeVar

import httpx
from nonebot import logger
from nonebot.matcher import Matcher
from nonebot.params import Depends
from pypinyin import lazy_pinyin
from seerapi_models import (
    BattleEffectORM,
    ElementTypeORM,
    EquipORM,
    ErrorCodeORM,
    GemCategoryORM,
    GemORM,
    MintmarkClassCategoryORM,
    MintmarkORM,
    PetORM,
    PetSkinORM,
    SuitORM,
    TitlePartORM,
    TypeCombinationORM,
)
from seerapi_models.build_model import BaseResModel
from sqlalchemy import text
from sqlalchemy.engine.base import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SQLModelSession
from sqlmodel import and_, col, func, or_, select

# require("ironsbot.plugins.db_sync")
from ironsbot.plugins.db_sync import (
    GetFingerprintFn,
    register_database,
    register_local_database,
    register_update_hook,
)
from ironsbot.plugins.db_sync.manager import db_manager
from ironsbot.utils.parse_arg import parse_string_arg

from .config import plugin_config
from .orm import BaseAliasORM, GemAliasORM, PetAliasORM
from .push_notify import build_updated_hook

_SEERAPI_DB = "seerapi"
_ALIAS_DB = "aliases"


def _register(
    name: str,
    sync_url: str,
    interval: int,
    local_path: str,
    get_fingerprint: GetFingerprintFn | None = None,
) -> None:
    if sync_url:
        register_database(
            name,
            sync_url=sync_url,
            sync_interval_minutes=interval,
            get_fingerprint=get_fingerprint,
        )
    else:
        register_local_database(name, file_path=local_path)


async def _get_seerapi_fingerprint(client: httpx.AsyncClient) -> str:
    response = await client.get(plugin_config.seerapi_fingerprint_url)
    return response.text


async def _get_alias_fingerprint(client: httpx.AsyncClient) -> str:
    response = await client.get(plugin_config.alias_fingerprint_url)
    return response.text


_register(
    _SEERAPI_DB,
    plugin_config.seerapi_sync_url,
    plugin_config.seerapi_sync_interval_minutes,
    plugin_config.seerapi_local_path,
    _get_seerapi_fingerprint if plugin_config.seerapi_fingerprint_url else None,
)
_register(
    _ALIAS_DB,
    plugin_config.alias_sync_url,
    plugin_config.alias_sync_interval_minutes,
    plugin_config.alias_local_path,
    _get_alias_fingerprint if plugin_config.alias_fingerprint_url else None,
)

_PINYIN_FTS_TABLE = "pinyin_fts"

_PINYIN_FTS_SOURCES: dict[str, str] = {
    "pet": "SELECT id, name FROM pet",
}


def _build_pinyin_fts(engine: Engine) -> None:
    """在内存引擎中为已注册的源表构建拼音 FTS5 索引。"""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE VIRTUAL TABLE [{_PINYIN_FTS_TABLE}] USING fts5("
                "source_table, pinyin_full, pinyin_initials, "
                "tokenize='trigram')"
            )
        )
        for source_table, query in _PINYIN_FTS_SOURCES.items():
            rows = conn.execute(text(query)).fetchall()
            for row_id, name in rows:
                syllables = lazy_pinyin(_strip_special(name))
                full = "".join(syllables)
                initials = "".join(s[0] for s in syllables if s)
                conn.execute(
                    text(
                        f"INSERT INTO [{_PINYIN_FTS_TABLE}]"
                        "(rowid, source_table, pinyin_full, pinyin_initials) "
                        "VALUES (:id, :src, :full, :initials)"
                    ),
                    {
                        "id": row_id,
                        "src": source_table,
                        "full": full,
                        "initials": initials,
                    },
                )
        conn.commit()
    logger.debug(f"已构建拼音 FTS5 索引，源表: {list(_PINYIN_FTS_SOURCES)}")


db_manager.register_post_load_hook(_SEERAPI_DB, _build_pinyin_fts)

# 数据库更新推送：seerapi / aliases 同步更新后向「数据库更新」主题订阅者推送
register_update_hook(_SEERAPI_DB, build_updated_hook(_SEERAPI_DB))
register_update_hook(_ALIAS_DB, build_updated_hook(_ALIAS_DB))

_T_Model = TypeVar("_T_Model", bound=BaseResModel)
_T_Model_co = TypeVar("_T_Model_co", bound=BaseResModel, covariant=True)

_IGNORED_CHARS = ".·・•‧∙⋅。—\u2013-_/ "
_IGNORED_CHARS_PATTERN = re.compile(f"[{re.escape(_IGNORED_CHARS)}]")


def _strip_special(text: str) -> str:
    return _IGNORED_CHARS_PATTERN.sub("", text)


def _col_strip_special(column: Any) -> Any:
    """构建一个 SQL 表达式，将列中的特殊字符逐个替换为空字符串。"""
    expr = column
    for char in _IGNORED_CHARS:
        expr = func.replace(expr, char, "")
    return expr


def _session_factory(
    db_name: str,
) -> Callable[..., AsyncGenerator[SQLModelSession, None]]:
    async def _session_generator(
        matcher: Matcher,
    ) -> AsyncGenerator[SQLModelSession, None]:
        gen = db_manager.get_session(db_name)
        if gen is None:
            await matcher.finish(
                f"❌数据库 '{db_name}' 未注册，无法使用此命令\n"
                "🔧请将命令和这条消息反馈给机器人维护者吧~"
            )
        try:
            yield next(gen)
        finally:
            gen.close()

    return _session_generator


SeerAPISession = Annotated[SQLModelSession, Depends(_session_factory(_SEERAPI_DB))]
AliasSession = Annotated[SQLModelSession, Depends(_session_factory(_ALIAS_DB))]
AllSessions = Annotated[
    dict[str, SQLModelSession], Depends(db_manager.get_all_sessions)
]


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
            stripped_arg = arg.strip()
            statement = select(self.alias_model).where(
                _col_strip_special(col(self.alias_model.name)).like(f"%{stripped_arg}%")
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


def _pinyin_syllables_contain(
    target_syllables: list[str],
    input_syllables: list[str],
) -> bool:
    """判断 input_syllables 是否作为连续子序列精确出现在 target_syllables 中。"""
    n = len(input_syllables)
    return any(
        target_syllables[i : i + n] == input_syllables
        for i in range(len(target_syllables) - n + 1)
    )


class PinyinResolver(Generic[_T_Model]):
    """通过汉语拼音（全拼或首字母）搜索模型对象，基于 FTS5 索引。

    当用户输入包含中文时，会按音节精确匹配，
    例如"库马"(ku ma)匹配"库玛"但不匹配"库曼"(ku man)。
    """

    __slots__ = ("db_name", "model", "name_attr", "source_table")

    def __init__(
        self,
        model: type[_T_Model],
        *,
        source_table: str,
        db_name: str = _SEERAPI_DB,
        name_attr: str = "name",
    ) -> None:
        self.model = model
        self.source_table = source_table
        self.db_name = db_name
        self.name_attr = name_attr

    def __repr__(self) -> str:
        return (
            "PinyinResolver("
            f"model={self.model.resource_name()!r}, "
            f"source_table={self.source_table!r}, "
            f"db_name={self.db_name!r}"
            ")"
        )

    @staticmethod
    def _to_pinyin_needle(
        arg: str,
    ) -> tuple[str, list[str] | None] | None:
        """将用户输入转换为拼音搜索字符串。

        返回 (joined_pinyin, syllables)，其中 syllables 仅在输入包含
        非 ASCII 字符（如中文）时非 None，用于后续音节级精确过滤。
        """
        stripped = _strip_special(arg)
        if not stripped:
            return None
        if stripped.isascii():
            if not stripped.isalpha():
                return None
            return (stripped.lower(), None)
        syllables = [s.lower() for s in lazy_pinyin(stripped)]
        needle = "".join(syllables)
        return (needle, syllables) if needle else None

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[_T_Model]:
        if len(arg) < 2:  # noqa: PLR2004
            return ()
        result = self._to_pinyin_needle(arg)
        if result is None:
            return ()
        needle, input_syllables = result

        session = sessions.get(self.db_name)
        if session is None:
            logger.warning(f"{self!r}: 未找到数据库会话")
            return ()

        try:
            rows = session.execute(
                text(
                    f"SELECT rowid FROM [{_PINYIN_FTS_TABLE}] "
                    "WHERE source_table = :src "
                    "AND (pinyin_full MATCH :q OR pinyin_initials MATCH :q)"
                ),
                {"src": self.source_table, "q": f'"{needle}"'},
            ).fetchall()
        except OperationalError:
            logger.opt(exception=True).debug(
                f"{self!r}: FTS5 查询失败，索引可能尚未构建"
            )
            return ()

        ids = [r[0] for r in rows]
        if not ids:
            return ()

        objs = session.exec(select(self.model).where(col(self.model.id).in_(ids))).all()

        if input_syllables is None:
            return objs

        return [
            obj
            for obj in objs
            if _pinyin_syllables_contain(
                [
                    s.lower()
                    for s in lazy_pinyin(
                        _strip_special(getattr(obj, self.name_attr, ""))
                    )
                ],
                input_syllables,
            )
        ]


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


PetDataGetter = Getter(
    PetORM,
    IdResolver(PetORM),
    NameResolver(PetORM),
    AliasResolver(PetORM, PetAliasORM),
    PinyinResolver(PetORM, source_table="pet"),
)


def GetPetData() -> Any:
    return Depends(PetDataGetter)


MintmarkDataGetter = Getter(
    MintmarkORM,
    IdResolver(MintmarkORM),
    NameResolver(MintmarkORM),
)


def GetMintmarkData() -> Any:
    return Depends(MintmarkDataGetter)


MintmarkClassDataGetter = Getter(
    MintmarkClassCategoryORM,
    # IdResolver(MintmarkClassCategoryORM),
    NameResolver(MintmarkClassCategoryORM),
)


def GetMintmarkClassData() -> Any:
    return Depends(MintmarkClassDataGetter)


PetSkinDataGetter = Getter(
    PetSkinORM,
    IdResolver(PetSkinORM),
    NameResolver(PetSkinORM),
)


def GetPetSkinData() -> Any:
    return Depends(PetSkinDataGetter)


GemDataGetter = Getter(
    GemORM,
    IdResolver(GemORM),
    NameResolver(GemORM),
    AliasResolver(GemORM, GemAliasORM),
)


def GetGemData() -> Any:
    return Depends(GemDataGetter)


GemCategoryDataGetter = Getter(
    GemCategoryORM,
    # IdResolver(GemCategoryORM),
    NameResolver(GemCategoryORM),
)


def GetGemCategoryData() -> Any:
    return Depends(GemCategoryDataGetter)


SuitDataGetter = Getter(
    SuitORM,
    IdResolver(SuitORM),
    NameResolver(SuitORM),
)


def GetSuitData() -> Any:
    return Depends(SuitDataGetter)


EquipDataGetter = Getter(
    EquipORM,
    IdResolver(EquipORM),
    NameResolver(EquipORM),
)


def GetEquipData() -> Any:
    return Depends(EquipDataGetter)


TitleDataGetter = Getter(
    TitlePartORM,
    IdResolver(TitlePartORM),
    NameResolver(TitlePartORM),
)


def GetTitleData() -> Any:
    return Depends(TitleDataGetter)


ErrorCodeGetter = Getter(
    ErrorCodeORM,
    IdResolver(ErrorCodeORM),
)


def GetErrorCodeData() -> Any:
    return Depends(ErrorCodeGetter)


class TypeCombinationResolver:
    """将用户输入拆分为单属性名，再按 ID 组合查询 TypeCombinationORM。

    支持任意顺序输入：如 "火战斗" 和 "战斗火" 都能匹配到同一条双属性记录。
    """

    __slots__ = ("db_name",)

    def __init__(self, *, db_name: str = _SEERAPI_DB) -> None:
        self.db_name = db_name

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[TypeCombinationORM]:
        session = sessions.get(self.db_name)
        if session is None:
            logger.warning("TypeCombinationResolver: 未找到数据库会话")
            return ()

        stripped = _strip_special(arg)
        if not stripped:
            return ()

        all_types = session.exec(select(ElementTypeORM)).all()
        name_to_id: dict[str, int] = {t.name: t.id for t in all_types}

        # 单属性：整个输入是一个合法属性名
        if stripped in name_to_id:
            tid = name_to_id[stripped]
            results = list(
                session.exec(
                    select(TypeCombinationORM).where(
                        TypeCombinationORM.primary_id == tid,
                        TypeCombinationORM.secondary_id is None,
                    )
                ).all()
            )
            if results:
                return results

        # 双属性：尝试在每个位置拆分为两个合法属性名
        found: dict[int, TypeCombinationORM] = {}
        for i in range(1, len(stripped)):
            left, right = stripped[:i], stripped[i:]
            if left not in name_to_id or right not in name_to_id:
                continue
            a, b = name_to_id[left], name_to_id[right]
            combos = session.exec(
                select(TypeCombinationORM).where(
                    or_(
                        and_(
                            TypeCombinationORM.primary_id == a,
                            TypeCombinationORM.secondary_id == b,
                        ),
                        and_(
                            TypeCombinationORM.primary_id == b,
                            TypeCombinationORM.secondary_id == a,
                        ),
                    )
                )
            ).all()
            for combo in combos:
                found.setdefault(combo.id, combo)

        return tuple(found.values())


TypeCombinationDataGetter = Getter(
    TypeCombinationORM,
    IdResolver(TypeCombinationORM),
    NameResolver(TypeCombinationORM),
    TypeCombinationResolver(),
)


def GetTypeCombinationData() -> Any:
    return Depends(TypeCombinationDataGetter)


BattleEffectDataGetter = Getter(
    BattleEffectORM,
    IdResolver(BattleEffectORM),
    NameResolver(BattleEffectORM),
)


def GetBattleEffectData() -> Any:
    return Depends(BattleEffectDataGetter)
