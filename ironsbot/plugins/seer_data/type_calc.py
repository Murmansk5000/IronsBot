# SPDX-License-Identifier: MIT
"""赛尔号属性克制倍率计算（纯计算逻辑，不涉及命令注册或渲染）。

单属性克制关系来自数据表；双属性倍率按游戏规则由两个单属性系数混合：
- 两系数均为 2 → 4
- 任一系数为 0 → (c1 + c2) / 4
- 其余情况 → (c1 + c2) / 2
"""

from seerapi_models import ElementTypeRelationORM, TypeCombinationORM
from sqlmodel import Session, select

__all__ = [
    "calc_attack_table",
    "calc_defense_table",
    "calc_multiplier",
    "calc_type_multiplier",
    "load_relation_map",
]

_SUPER_EFFECTIVE = 2.0
"""克制倍率阈值。"""

_IMMUNE = 0.0
"""免疫倍率阈值。"""

RelationMap = dict[tuple[int, int], float]
"""(攻击方单属性ID, 防守方单属性ID) → 克制倍率。"""


def load_relation_map(session: Session) -> RelationMap:
    """一次性加载所有单属性克制关系到内存。"""
    rows = session.exec(
        select(
            ElementTypeRelationORM.source_id,
            ElementTypeRelationORM.target_id,
            ElementTypeRelationORM.multiple,
        )
    ).all()
    return {(src, tgt): mul for src, tgt, mul in rows}


def _load_combinations(session: Session) -> list[TypeCombinationORM]:
    """加载所有属性组合。"""
    return list(session.exec(select(TypeCombinationORM)).all())


def _lookup(table: RelationMap, attack_id: int, defend_id: int) -> float:
    return table.get((attack_id, defend_id), 1.0)


def _mix(first: float, second: float) -> float:
    """涉及双属性时，根据两个单属性系数计算混合倍率（单攻双 / 双攻单通用）。"""
    total = first + second
    if first == _SUPER_EFFECTIVE and second == _SUPER_EFFECTIVE:
        return total  # 4
    if _IMMUNE in (first, second):
        return total / 4
    return total / 2


def _double_attacks_single(
    table: RelationMap,
    attack_primary_id: int,
    attack_secondary_id: int,
    defend_id: int,
) -> float:
    """双属性攻击单属性。"""
    return _mix(
        _lookup(table, attack_primary_id, defend_id),
        _lookup(table, attack_secondary_id, defend_id),
    )


def calc_multiplier(
    table: RelationMap,
    attacker: TypeCombinationORM,
    defender: TypeCombinationORM,
) -> float:
    """基于预加载的关系表，计算攻击方属性组合对防守方属性组合的克制倍率。"""
    attack_secondary = attacker.secondary_id
    defend_secondary = defender.secondary_id

    if attack_secondary is None and defend_secondary is None:
        # 单属性攻击单属性
        return _lookup(table, attacker.primary_id, defender.primary_id)

    if attack_secondary is None and defend_secondary is not None:
        # 单属性攻击双属性
        return _mix(
            _lookup(table, attacker.primary_id, defender.primary_id),
            _lookup(table, attacker.primary_id, defend_secondary),
        )

    if attack_secondary is not None and defend_secondary is None:
        # 双属性攻击单属性
        return _double_attacks_single(
            table,
            attacker.primary_id,
            attack_secondary,
            defender.primary_id,
        )

    assert attack_secondary is not None and defend_secondary is not None
    # 双属性攻击双属性
    first = _double_attacks_single(
        table,
        attacker.primary_id,
        attack_secondary,
        defender.primary_id,
    )
    second = _double_attacks_single(
        table,
        attacker.primary_id,
        attack_secondary,
        defend_secondary,
    )
    return (first + second) / 2


def calc_type_multiplier(
    session: Session,
    attacker: TypeCombinationORM,
    defender: TypeCombinationORM,
) -> float:
    """计算攻击方属性组合对防守方属性组合的克制倍率。"""
    return calc_multiplier(load_relation_map(session), attacker, defender)


def calc_attack_table(
    session: Session,
    attacker: TypeCombinationORM,
) -> list[tuple[TypeCombinationORM, float]]:
    """计算指定属性组合进攻所有属性组合的克制倍率表。

    返回 [(防守方属性组合, 克制倍率), ...]。
    """
    table = load_relation_map(session)
    return [
        (combo, calc_multiplier(table, attacker, combo))
        for combo in _load_combinations(session)
    ]


def calc_defense_table(
    session: Session,
    defender: TypeCombinationORM,
) -> list[tuple[TypeCombinationORM, float]]:
    """计算所有属性组合进攻指定属性组合的克制倍率表。

    返回 [(攻击方属性组合, 克制倍率), ...]。
    """
    table = load_relation_map(session)
    return [
        (combo, calc_multiplier(table, combo, defender))
        for combo in _load_combinations(session)
    ]
