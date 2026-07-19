# SPDX-License-Identifier: GPL-3.0-or-later
"""属性克制倍率计算（纯计算逻辑，不涉及命令注册或渲染）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from seerapi_models import ElementTypeORM
from seerapi_models.element_type import ElementTypeRelationORM, TypeCombinationORM
from sqlmodel import Session, select

_SUPER_EFFECTIVE = 2
"""克制倍率阈值。"""

_IMMUNE = 0
"""免疫倍率阈值。"""

RelationMap = dict[tuple[int, int], float]
"""(攻击方单属性ID, 防守方单属性ID) → 克制倍率。"""
_MAX_CUSTOM_TYPES = 2
_CUSTOM_SEPARATOR_TRANSLATION = str.maketrans(
    {"\uff0b": "+", "\uff0f": "/", "\uff5c": "|", "，": ",", "、": ","}
)
_CUSTOM_TYPE_SPLIT_PATTERN = re.compile(r"[+,/|\s]+")


@dataclass(frozen=True, slots=True)
class TypeMatchup:
    target: TypeCombinationORM
    attack_table: list[tuple[TypeCombinationORM, float]]
    defense_table: list[tuple[TypeCombinationORM, float]]
    cache_key: str


def _load_relations(session: Session) -> RelationMap:
    """一次性加载所有单属性克制关系到内存。"""
    rows = session.exec(
        select(
            ElementTypeRelationORM.source_id,
            ElementTypeRelationORM.target_id,
            ElementTypeRelationORM.multiple,
        )
    ).all()
    return {(src, tgt): mul for src, tgt, mul in rows}


def _lookup(table: RelationMap, atk_id: int, def_id: int) -> float:
    return table.get((atk_id, def_id), 1.0)


def _calc_mixed(c1: float, c2: float) -> float:
    """涉及双属性时，根据两个单属性系数计算混合倍率（单攻双 / 双攻单通用）。

    规则：
    - 两个系数都为 2 → 4（即 sum / 1）
    - 至少一个为 0 → sum / 4
    - 其余情况 → sum / 2
    """
    total = c1 + c2
    if c1 == _SUPER_EFFECTIVE and c2 == _SUPER_EFFECTIVE:
        return total  # 4
    if _IMMUNE in (c1, c2):
        return total / 4
    return total / 2


def _double_attacks_single(
    table: RelationMap,
    atk_primary_id: int,
    atk_secondary_id: int,
    def_id: int,
) -> float:
    """双属性攻击单属性。"""
    c1 = _lookup(table, atk_primary_id, def_id)
    c2 = _lookup(table, atk_secondary_id, def_id)
    return _calc_mixed(c1, c2)


def _calc_multiplier(
    table: RelationMap,
    attacker: TypeCombinationORM,
    defender: TypeCombinationORM,
) -> float:
    """纯计算：基于预加载的关系表计算属性克制倍率。"""
    atk_sec = attacker.secondary_id
    def_sec = defender.secondary_id

    if atk_sec is None and def_sec is None:
        return _lookup(table, attacker.primary_id, defender.primary_id)

    if atk_sec is None and def_sec is not None:
        c1 = _lookup(table, attacker.primary_id, defender.primary_id)
        c2 = _lookup(table, attacker.primary_id, def_sec)
        return _calc_mixed(c1, c2)

    if atk_sec is not None and def_sec is None:
        return _double_attacks_single(
            table, attacker.primary_id, atk_sec, defender.primary_id
        )

    if atk_sec is None or def_sec is None:
        raise ValueError
    c1 = _double_attacks_single(
        table, attacker.primary_id, atk_sec, defender.primary_id
    )
    c2 = _double_attacks_single(table, attacker.primary_id, atk_sec, def_sec)
    return (c1 + c2) / 2


def load_type_matchup(
    session: Session,
    *,
    target: TypeCombinationORM,
    cache_key: str | None = None,
) -> TypeMatchup:
    table = _load_relations(session)
    combinations = list(session.exec(select(TypeCombinationORM)).all())
    return TypeMatchup(
        target=target,
        attack_table=[
            (combo, _calc_multiplier(table, target, combo))
            for combo in combinations
        ],
        defense_table=[
            (combo, _calc_multiplier(table, combo, target))
            for combo in combinations
        ],
        cache_key=cache_key or str(target.id),
    )


def load_type_matchup_by_id(
    session: Session,
    *,
    type_id: int,
) -> TypeMatchup | None:
    target = session.get(TypeCombinationORM, type_id)
    return None if target is None else load_type_matchup(session, target=target)


def load_custom_type_matchup(
    session: Session,
    *,
    arg: str,
) -> TypeMatchup | None:
    all_types = session.exec(select(ElementTypeORM)).all()
    name_to_type = {element.name: element for element in all_types}
    type_names = _split_custom_type_names(arg, set(name_to_type))
    if type_names is None:
        return None

    elements = [name_to_type[name] for name in type_names]
    secondary_id = elements[1].id if len(elements) == _MAX_CUSTOM_TYPES else None
    custom_name = "".join(element.name for element in elements)
    target = TypeCombinationORM(
        id=-1,
        name=f"{custom_name}（DIY 属性）",
        name_en="custom",
        primary_id=elements[0].id,
        secondary_id=secondary_id,
    )
    ids = sorted(element.id for element in elements)
    return load_type_matchup(
        session,
        target=target,
        cache_key="custom_type_matchup_" + "_".join(map(str, ids)),
    )


def _split_custom_type_names(
    arg: str,
    all_names: set[str],
) -> tuple[str, ...] | None:
    normalized = arg.translate(_CUSTOM_SEPARATOR_TRANSLATION).strip()
    if not normalized:
        return None

    parts = tuple(part for part in _CUSTOM_TYPE_SPLIT_PATTERN.split(normalized) if part)
    if len(parts) == 1:
        token = parts[0]
        if token in all_names:
            return (token,)
        candidates = [
            (token[:index], token[index:])
            for index in range(1, len(token))
            if token[:index] in all_names and token[index:] in all_names
        ]
        return candidates[0] if len(candidates) == 1 else None
    if (
        len(parts) == _MAX_CUSTOM_TYPES
        and parts[0] != parts[1]
        and all(part in all_names for part in parts)
    ):
        return parts
    return None
