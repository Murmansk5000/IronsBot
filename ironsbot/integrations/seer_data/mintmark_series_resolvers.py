# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

from nonebot import logger
from seerapi_models import MintmarkClassCategoryORM, MintmarkORM
from seerapi_models.mintmark import UniversalPartORM
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ironsbot.config.loader import get_app_config

from .normalization import normalize_key
from .orm import MintmarkClassAliasORM, MintmarkSeriesMemberORM

if TYPE_CHECKING:
    from collections.abc import Iterable

_SEERAPI_DB = "seerapi"
_ALIAS_DB = "aliases"
_SERIES_ORDINAL_PATTERN = re.compile(r"(?P<prefix>.+?)(?P<ordinal>\d{1,2})$")
_MINTMARK_TYPE_MARKERS = ("双攻", "双刀", "双防", "物", "特", "攻", "速", "盾", "体")
_MINTMARK_TYPE_QUERY_CHARS = frozenset(("物", "特", "攻", "速", "盾", "体"))
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


def _is_valid_series_ordinal_prefix(prefix: str) -> bool:
    normalized = normalize_key(prefix)
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
    ):
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
        if normalized_prefix in normalize_key(mintmark_class.name)
    ]
    return matches if len(matches) == 1 else []


def _is_mintmark_type_query(query: str) -> bool:
    normalized = query.replace("双刀", "双攻").replace("双防", "盾")
    if normalized == "双攻":
        return True
    if normalized.startswith("双攻"):
        normalized = normalized.removeprefix("双攻")
    return bool(normalized) and all(
        char in _MINTMARK_TYPE_QUERY_CHARS for char in normalized
    )


def _iter_series_type_splits(arg: str) -> Iterable[tuple[str, str]]:
    stripped = arg.strip()
    for index, _char in enumerate(stripped):
        prefix = stripped[:index].strip()
        type_query = stripped[index:].strip()
        if (
            prefix
            and type_query.startswith(_MINTMARK_TYPE_MARKERS)
            and _is_mintmark_type_query(type_query)
        ):
            yield prefix, type_query


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


def resolve_custom_mintmark_series(
    sessions: dict[str, SQLModelSession],
    arg: str,
) -> tuple[MintmarkORM, ...]:
    alias_session = sessions.get(_ALIAS_DB)
    data_session = sessions.get(_SEERAPI_DB)
    if alias_session is None or data_session is None:
        return ()

    try:
        members = list(alias_session.exec(select(MintmarkSeriesMemberORM)).all())
    except OperationalError:
        return ()
    if not members:
        return ()

    ids: list[int] = []
    type_query = ""
    normalized_arg = normalize_key(arg)
    exact_members = [
        member for member in members if normalize_key(member.name) == normalized_arg
    ]
    if exact_members:
        ids = sorted({member.target_id for member in exact_members})
    elif (parsed := _parse_series_ordinal_arg(arg)) is not None:
        raw_prefix, ordinal = parsed
        series_ids = sorted(
            {
                member.target_id
                for member in members
                if normalize_key(member.name) == normalize_key(raw_prefix)
            }
        )
        if 0 < ordinal <= len(series_ids):
            ids = [series_ids[ordinal - 1]]
    else:
        for raw_prefix, candidate_type_query in _iter_series_type_splits(arg):
            series_ids = sorted(
                {
                    member.target_id
                    for member in members
                    if normalize_key(member.name) == normalize_key(raw_prefix)
                }
            )
            if series_ids:
                ids = series_ids
                type_query = candidate_type_query
                break

    result = tuple(
        mintmark
        for target_id in ids
        if (mintmark := data_session.get(MintmarkORM, target_id)) is not None
    )
    if not type_query:
        return result
    return tuple(
        mintmark
        for mintmark in result
        if _mintmark_type_matches(
            _mintmark_type_description(mintmark),
            type_query,
        )
    )


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

    def __call__(
        self,
        sessions: dict[str, SQLModelSession],
        arg: str,
    ) -> Iterable[MintmarkORM]:
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
            on_clause = cast("Any", UniversalPartORM.mintmark_id == MintmarkORM.id)
            order_column = cast("Any", MintmarkORM.id)
            statement = (
                select(MintmarkORM)
                .join(
                    UniversalPartORM,
                    on_clause,
                )
                .where(UniversalPartORM.mintmark_class_id == class_id)
                .order_by(order_column)
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

    def _resolve_class_ids(
        self,
        sessions: dict[str, SQLModelSession],
        raw_prefix: str,
    ) -> list[int]:
        data_session = sessions.get(self.data_db)
        if data_session is None:
            logger.warning(f"{self!r}: 未找到数据数据库会话")
            return []

        normalized_prefix = normalize_key(raw_prefix)
        candidates = {normalized_prefix}
        if not normalized_prefix.endswith("系列"):
            candidates.add(normalize_key(f"{raw_prefix}系列"))

        classes = data_session.exec(select(MintmarkClassCategoryORM)).all()
        class_ids: list[int] = [
            mintmark_class.id
            for mintmark_class in classes
            if normalize_key(mintmark_class.name) in candidates
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
            if normalize_key(alias.name) in candidates
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

    def __call__(
        self,
        sessions: dict[str, SQLModelSession],
        arg: str,
    ) -> Iterable[MintmarkORM]:
        class_ids: list[int] = []
        type_query = ""
        ordinal_resolver = MintmarkSeriesOrdinalResolver(
            alias_db=self.alias_db,
            data_db=self.data_db,
        )
        for raw_prefix, candidate_type_query in _iter_series_type_splits(arg):
            class_ids = ordinal_resolver._resolve_class_ids(sessions, raw_prefix)
            if class_ids:
                type_query = candidate_type_query
                break

        if not class_ids:
            return ()

        data_session = sessions.get(self.data_db)
        if data_session is None:
            logger.warning(f"{self!r}: 未找到数据数据库会话")
            return ()

        merge_connected = get_app_config().seer.mintmark.merge_connected
        result: list[MintmarkORM] = []
        for class_id in class_ids:
            on_clause = cast("Any", UniversalPartORM.mintmark_id == MintmarkORM.id)
            order_column = cast("Any", MintmarkORM.id)
            statement = (
                select(MintmarkORM)
                .join(
                    UniversalPartORM,
                    on_clause,
                )
                .where(UniversalPartORM.mintmark_class_id == class_id)
                .order_by(order_column)
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
