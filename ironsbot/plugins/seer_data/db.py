# SPDX-License-Identifier: MIT
# ruff: noqa: N802, TRY003

import re
from collections.abc import AsyncGenerator, Callable, Iterable
from typing import Annotated, Any, Generic, Protocol, TypeVar

import httpx
from nonebot import logger
from nonebot.matcher import Matcher
from nonebot.params import Depends
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
from seerapi_models.mintmark import UniversalPartORM
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SQLModelSession
from sqlmodel import and_, col, func, or_, select

from ironsbot.config import get_app_config
from ironsbot.config.models.runtime import RemoteBuildConfig

# require("ironsbot.plugins.db_sync")
from ironsbot.plugins.db_sync import (
    GetFingerprintFn,
    register_database,
    register_local_database,
)
from ironsbot.plugins.db_sync.manager import db_manager
from ironsbot.utils.parse_arg import parse_string_arg

from .config import get_data_sync_config
from .orm import (
    BaseAliasORM,
    GemAliasORM,
    MintmarkAliasORM,
    MintmarkClassAliasORM,
    PetAliasORM,
)

_SEERAPI_DB = "seerapi"
_ALIAS_DB = "aliases"


def _register(  # noqa: PLR0913
    name: str,
    sync_url: str,
    interval: int,
    local_path: str,
    get_fingerprint: GetFingerprintFn | None = None,
    remote_build: RemoteBuildConfig | None = None,
) -> None:
    if sync_url:
        register_database(
            name,
            sync_url=sync_url,
            sync_interval_minutes=interval,
            get_fingerprint=get_fingerprint,
            local_path=local_path,
            remote_build=remote_build,
        )
    else:
        register_local_database(name, file_path=local_path)


def _fingerprint_getter(url: str) -> GetFingerprintFn | None:
    if not url:
        return None

    async def _get_fingerprint(client: httpx.AsyncClient) -> str:
        response = await client.get(url)
        return response.text

    return _get_fingerprint


def _register_source(name: str) -> None:
    source = get_data_sync_config().sources.get(name)
    if source is None:
        logger.warning(f"数据源 '{name}' 未在 runtime.data_sync.sources 中配置")
        return

    _register(
        name,
        source.url,
        source.interval_minutes,
        source.local_path,
        _fingerprint_getter(source.fingerprint_url),
        source.remote_build,
    )


_register_source(_SEERAPI_DB)
_register_source(_ALIAS_DB)

_T_Model = TypeVar("_T_Model", bound=BaseResModel)
_T_Model_co = TypeVar("_T_Model_co", bound=BaseResModel, covariant=True)

_IGNORED_CHARS = ".·・•‧∙⋅。—\u2013-_/ "
_IGNORED_CHARS_PATTERN = re.compile(f"[{re.escape(_IGNORED_CHARS)}]")
_SERIES_ORDINAL_PATTERN = re.compile(r"(?P<prefix>.+?)(?P<ordinal>\d{1,2})$")
_MINTMARK_TYPE_SUFFIXES = (
    "物攻盾体",
    "特攻盾体",
    "物攻盾",
    "特攻盾",
    "物攻体",
    "特攻体",
    "物盾体",
    "特盾体",
    "物速",
    "特速",
    "物攻",
    "特攻",
    "物体",
    "特体",
    "物盾",
    "特盾",
    "双攻",
    "双刀",
    "双防",
    "盾体",
    "双防体",
    "攻盾",
    "攻体",
    "速",
    "盾",
    "体",
    "物",
    "特",
    "攻",
)
_ATTACK_MARK_THRESHOLD = 54
_SPEED_MARK_THRESHOLD = 40
_DEFENSE_MARK_THRESHOLD = 40
_HP_MARK_THRESHOLD = 100
_SERIES_ORDINAL_SELECTORS = {
    1: ("physical", "spd"),
    2: ("special", "spd"),
    3: ("physical", "atk"),
    4: ("special", "sp_atk"),
    5: ("physical", "hp"),
    6: ("special", "hp"),
    7: ("physical", "dual_def"),
    8: ("special", "dual_def"),
}
_EQUAL_DUAL_ATTACK_HP_ORDINAL = 9
_EQUAL_DUAL_ATTACK_SPEED_ORDINAL = 10


def _strip_special(text: str) -> str:
    return _IGNORED_CHARS_PATTERN.sub("", text)


def _normalize_key(text: str) -> str:
    return _strip_special(text).casefold()


def _is_valid_series_ordinal_prefix(prefix: str) -> bool:
    normalized = _normalize_key(prefix)
    return bool(normalized) and not normalized.isdigit()


def _parse_series_ordinal_arg(arg: str) -> tuple[str, int] | None:
    match = _SERIES_ORDINAL_PATTERN.fullmatch(arg.strip())
    if match is None:
        return None

    raw_prefix = match.group("prefix")
    if not _is_valid_series_ordinal_prefix(raw_prefix):
        return None

    ordinal = int(match.group("ordinal"))
    if ordinal < 1:
        return None

    return raw_prefix, ordinal


def _mintmark_type_description(mintmark: MintmarkORM) -> str:
    part = mintmark.ability_part or mintmark.universal_part
    if part is None:
        return ""

    attr = part.max_attr_value.to_model()
    if isinstance(part, UniversalPartORM) and part.extra_attr_value:
        attr = attr + part.extra_attr_value.to_model()
    attr = attr.round()

    strings: list[str] = []
    if attr.atk and not attr.sp_atk:
        strings.append("物")
    elif attr.sp_atk and not attr.atk:
        strings.append("特")
    elif attr.atk and attr.sp_atk:
        strings.append("双攻")

    if (
        attr.atk >= _ATTACK_MARK_THRESHOLD
        or attr.sp_atk >= _ATTACK_MARK_THRESHOLD
    ) and attr.spd < _SPEED_MARK_THRESHOLD:
        strings.append("攻")
    if attr.spd >= _SPEED_MARK_THRESHOLD:
        strings.append("速")
    if (
        attr.def_ >= _DEFENSE_MARK_THRESHOLD
        or attr.sp_def >= _DEFENSE_MARK_THRESHOLD
    ):
        strings.append("盾")
    if attr.hp >= _HP_MARK_THRESHOLD:
        strings.append("体")

    return "".join(strings)


def _mintmark_attr(mintmark: MintmarkORM) -> Any | None:
    part = mintmark.ability_part or mintmark.universal_part
    if part is None:
        return None

    attr = part.max_attr_value.to_model()
    if isinstance(part, UniversalPartORM) and part.extra_attr_value:
        attr = attr + part.extra_attr_value.to_model()
    return attr.round()


def _select_series_ordinal_mintmarks(
    mintmarks: list[MintmarkORM],
    ordinal: int,
) -> tuple[MintmarkORM, ...]:
    if ordinal in _SERIES_ORDINAL_SELECTORS:
        attack_kind, metric = _SERIES_ORDINAL_SELECTORS[ordinal]
        candidates = [
            mintmark
            for mintmark in mintmarks
            if _mintmark_attack_kind(mintmark) == attack_kind
        ]
        return _select_highest_metric(candidates, metric)

    if ordinal == _EQUAL_DUAL_ATTACK_HP_ORDINAL:
        return tuple(
            mintmark
            for mintmark in mintmarks
            if _is_equal_dual_attack_mintmark(mintmark)
            and (attr := _mintmark_attr(mintmark)) is not None
            and attr.spd == 0
            and attr.hp > 0
        )

    if ordinal == _EQUAL_DUAL_ATTACK_SPEED_ORDINAL:
        return tuple(
            mintmark
            for mintmark in mintmarks
            if _is_equal_dual_attack_mintmark(mintmark)
            and (attr := _mintmark_attr(mintmark)) is not None
            and attr.spd > 0
            and attr.hp == 0
        )

    return ()


def _mintmark_attack_kind(mintmark: MintmarkORM) -> str | None:
    attr = _mintmark_attr(mintmark)
    if attr is None:
        return None
    if attr.atk > 0 and attr.sp_atk == 0:
        return "physical"
    if attr.sp_atk > 0 and attr.atk == 0:
        return "special"
    return None


def _is_equal_dual_attack_mintmark(mintmark: MintmarkORM) -> bool:
    attr = _mintmark_attr(mintmark)
    return attr is not None and attr.atk > 0 and attr.atk == attr.sp_atk


def _select_highest_metric(
    mintmarks: list[MintmarkORM],
    metric: str,
) -> tuple[MintmarkORM, ...]:
    values = [
        (mintmark, _mintmark_metric_value(mintmark, metric))
        for mintmark in mintmarks
    ]
    values = [(mintmark, value) for mintmark, value in values if value > 0]
    if not values:
        return ()

    highest = max(value for _mintmark, value in values)
    return tuple(mintmark for mintmark, value in values if value == highest)


def _mintmark_metric_value(mintmark: MintmarkORM, metric: str) -> int:
    attr = _mintmark_attr(mintmark)
    if attr is None:
        return 0
    if metric == "dual_def":
        return attr.def_ + attr.sp_def
    return int(getattr(attr, metric, 0))


def _resolve_unique_partial_mintmark_class_id(
    classes: Iterable[MintmarkClassCategoryORM],
    normalized_prefix: str,
) -> list[int]:
    matches = [
        mintmark_class.id
        for mintmark_class in classes
        if normalized_prefix in _normalize_key(mintmark_class.name)
    ]
    return matches if len(matches) == 1 else []


def _split_series_type_arg(arg: str) -> tuple[str, str] | None:
    normalized_arg = _normalize_key(arg)
    for suffix in _MINTMARK_TYPE_SUFFIXES:
        normalized_suffix = _normalize_key(suffix)
        if normalized_arg.endswith(normalized_suffix):
            prefix = arg[: len(arg) - len(suffix)].strip()
            return (prefix, suffix) if prefix else None
    return None


def _mintmark_type_matches(description: str, query: str) -> bool:
    if not description:
        return False
    query = query.replace("双刀", "双攻").replace("双防", "盾")

    if query == "双攻":
        return "双攻" in description
    if query == "盾":
        return "盾" in description

    required = {
        char
        for char in ("物", "特", "攻", "速", "盾", "体")
        if char in query
    }
    return bool(required) and all(
        _mintmark_type_part_matches(description, char)
        for char in required
    )


def _mintmark_type_part_matches(description: str, char: str) -> bool:
    if char == "物":
        return "物" in description or "双攻" in description
    if char == "特":
        return "特" in description or "双攻" in description
    return char in description


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


class MintmarkSeriesOrdinalResolver:
    """Resolve inputs like ``九霄05`` or ``k1405`` to a mintmark in a series."""

    __slots__ = ("alias_db", "data_db")

    def __init__(
        self,
        *,
        alias_db: str = _ALIAS_DB,
        data_db: str = _SEERAPI_DB,
    ) -> None:
        self.alias_db = alias_db
        self.data_db = data_db

    def __repr__(self) -> str:
        return (
            "MintmarkSeriesOrdinalResolver("
            f"alias_db={self.alias_db!r}, data_db={self.data_db!r})"
        )

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[MintmarkORM]:
        parsed = _parse_series_ordinal_arg(arg)
        if parsed is None:
            return ()

        raw_prefix, ordinal = parsed
        class_ids = self._resolve_class_ids(sessions, raw_prefix)
        if not class_ids:
            return ()

        data_session = sessions.get(self.data_db)
        if data_session is None:
            logger.warning(f"{self!r}: 未找到数据数据库会话")
            return ()

        merge_connected = get_app_config().seer.mintmark.merge_connected
        for class_id in class_ids:
            statement = (
                select(MintmarkORM)
                .join(
                    UniversalPartORM,
                    UniversalPartORM.mintmark_id == MintmarkORM.id,
                )
                .where(UniversalPartORM.mintmark_class_id == class_id)
                .order_by(MintmarkORM.id)
            )
            mintmarks = list(data_session.exec(statement).all())
            if merge_connected:
                mintmarks = [
                    mintmark
                    for mintmark in mintmarks
                    if not mintmark.connected_universal_parts
                ]
            if result := _select_series_ordinal_mintmarks(mintmarks, ordinal):
                return result

        return ()

    def _resolve_class_ids(self, sessions: AllSessions, raw_prefix: str) -> list[int]:
        data_session = sessions.get(self.data_db)
        if data_session is None:
            logger.warning(f"{self!r}: 未找到数据数据库会话")
            return []

        normalized_prefix = _normalize_key(raw_prefix)
        candidates = {normalized_prefix}
        if not normalized_prefix.endswith("系列"):
            candidates.add(_normalize_key(f"{raw_prefix}系列"))

        classes = data_session.exec(select(MintmarkClassCategoryORM)).all()
        class_ids: list[int] = [
            mintmark_class.id
            for mintmark_class in classes
            if _normalize_key(mintmark_class.name) in candidates
        ]
        if class_ids:
            return class_ids

        alias_session = sessions.get(self.alias_db)
        if alias_session is None:
            logger.warning(f"{self!r}: 未找到别名数据库会话")
            return _resolve_unique_partial_mintmark_class_id(classes, normalized_prefix)

        try:
            aliases = alias_session.exec(select(MintmarkClassAliasORM)).all()
        except OperationalError as e:
            logger.error(f"MintmarkSeriesOrdinalResolver error: {e}")
            return _resolve_unique_partial_mintmark_class_id(classes, normalized_prefix)

        class_ids.extend(
            alias.target_id
            for alias in aliases
            if _normalize_key(alias.name) in candidates
        )

        return class_ids or _resolve_unique_partial_mintmark_class_id(
            classes,
            normalized_prefix,
        )


class MintmarkSeriesTypeResolver:
    """Resolve inputs like ``九霄盾`` or ``k14特攻`` to mintmarks in a series."""

    __slots__ = ("alias_db", "data_db")

    def __init__(
        self,
        *,
        alias_db: str = _ALIAS_DB,
        data_db: str = _SEERAPI_DB,
    ) -> None:
        self.alias_db = alias_db
        self.data_db = data_db

    def __repr__(self) -> str:
        return (
            "MintmarkSeriesTypeResolver("
            f"alias_db={self.alias_db!r}, data_db={self.data_db!r})"
        )

    def __call__(self, sessions: AllSessions, arg: str) -> Iterable[MintmarkORM]:
        parsed = _split_series_type_arg(arg)
        if parsed is None:
            return ()

        raw_prefix, type_query = parsed
        class_ids = MintmarkSeriesOrdinalResolver(
            alias_db=self.alias_db,
            data_db=self.data_db,
        )._resolve_class_ids(sessions, raw_prefix)
        if not class_ids:
            return ()

        data_session = sessions.get(self.data_db)
        if data_session is None:
            logger.warning(f"{self!r}: 未找到数据数据库会话")
            return ()

        merge_connected = get_app_config().seer.mintmark.merge_connected
        result: list[MintmarkORM] = []
        for class_id in class_ids:
            statement = (
                select(MintmarkORM)
                .join(
                    UniversalPartORM,
                    UniversalPartORM.mintmark_id == MintmarkORM.id,
                )
                .where(UniversalPartORM.mintmark_class_id == class_id)
                .order_by(MintmarkORM.id)
            )
            mintmarks = list(data_session.exec(statement).all())
            if merge_connected:
                mintmarks = [
                    mintmark
                    for mintmark in mintmarks
                    if not mintmark.connected_universal_parts
                ]
            result.extend(
                mintmark
                for mintmark in mintmarks
                if _mintmark_type_matches(
                    _mintmark_type_description(mintmark),
                    type_query,
                )
            )

        return tuple(result)


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
)


def GetPetData() -> Any:
    return Depends(PetDataGetter)


MintmarkDataGetter = Getter(
    MintmarkORM,
    IdResolver(MintmarkORM),
    NameResolver(MintmarkORM),
    AliasResolver(MintmarkORM, MintmarkAliasORM),
    MintmarkSeriesOrdinalResolver(),
    MintmarkSeriesTypeResolver(),
)


def GetMintmarkData() -> Any:
    return Depends(MintmarkDataGetter)


MintmarkClassDataGetter = Getter(
    MintmarkClassCategoryORM,
    # IdResolver(MintmarkClassCategoryORM),
    NameResolver(MintmarkClassCategoryORM),
    AliasResolver(MintmarkClassCategoryORM, MintmarkClassAliasORM),
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
