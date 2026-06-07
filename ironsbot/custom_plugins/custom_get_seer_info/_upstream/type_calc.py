# SPDX-License-Identifier: GPL-3.0-or-later
"""属性克制倍率计算（纯计算逻辑，不涉及命令注册或渲染）。"""

from seerapi_models.element_type import ElementTypeRelationORM, TypeCombinationORM
from sqlmodel import Session, select

_SUPER_EFFECTIVE = 2
"""克制倍率阈值。"""

_IMMUNE = 0
"""免疫倍率阈值。"""

RelationMap = dict[tuple[int, int], float]
"""(攻击方单属性ID, 防守方单属性ID) → 克制倍率。"""


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

    assert atk_sec is not None and def_sec is not None
    c1 = _double_attacks_single(
        table, attacker.primary_id, atk_sec, defender.primary_id
    )
    c2 = _double_attacks_single(table, attacker.primary_id, atk_sec, def_sec)
    return (c1 + c2) / 2


# ── 公开 API ──────────────────────────────────────────────


def calc_type_multiplier(
    session: Session,
    attacker: TypeCombinationORM,
    defender: TypeCombinationORM,
) -> float:
    """计算攻击方属性组合对防守方属性组合的克制倍率。"""
    table = _load_relations(session)
    return _calc_multiplier(table, attacker, defender)


def calc_attack_table(
    session: Session,
    attacker: TypeCombinationORM,
) -> list[tuple[TypeCombinationORM, float]]:
    """计算指定属性组合进攻所有属性组合的克制倍率表。

    返回 [(防守方属性组合, 克制倍率), ...]。
    """
    table = _load_relations(session)
    all_combos: list[TypeCombinationORM] = list(
        session.exec(select(TypeCombinationORM)).all()
    )
    return [(combo, _calc_multiplier(table, attacker, combo)) for combo in all_combos]


def calc_defense_table(
    session: Session,
    defender: TypeCombinationORM,
) -> list[tuple[TypeCombinationORM, float]]:
    """计算所有属性组合进攻指定属性组合的克制倍率表。

    返回 [(攻击方属性组合, 克制倍率), ...]。
    """
    table = _load_relations(session)
    all_combos: list[TypeCombinationORM] = list(
        session.exec(select(TypeCombinationORM)).all()
    )
    return [(combo, _calc_multiplier(table, combo, defender)) for combo in all_combos]
