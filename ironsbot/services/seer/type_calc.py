# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure element-type matchup calculations over detached official facts."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SUPER_EFFECTIVE = 2
_IMMUNE = 0
_MAX_CUSTOM_TYPES = 2
_CUSTOM_SEPARATOR_TRANSLATION = str.maketrans(
    {"＋": "+", "／": "/", "｜": "|", "，": ",", "、": ","}
)
_CUSTOM_TYPE_SPLIT_PATTERN = re.compile(r"[+,/|\s]+")

RelationMap = dict[tuple[int, int], float]


@dataclass(frozen=True, slots=True)
class ElementTypeSnapshot:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class TypeCombinationSnapshot:
    id: int
    name: str
    primary_id: int
    secondary_id: int | None


@dataclass(frozen=True, slots=True)
class TypeMatchupDataset:
    combinations: tuple[TypeCombinationSnapshot, ...]
    elements: tuple[ElementTypeSnapshot, ...]
    relations: tuple[tuple[int, int, float], ...]


@dataclass(frozen=True, slots=True)
class TypeMatchup:
    target: TypeCombinationSnapshot
    attack_table: list[tuple[TypeCombinationSnapshot, float]]
    defense_table: list[tuple[TypeCombinationSnapshot, float]]


def type_matchup_by_id(
    dataset: TypeMatchupDataset,
    *,
    type_id: int,
) -> TypeMatchup | None:
    target = next((item for item in dataset.combinations if item.id == type_id), None)
    return None if target is None else build_type_matchup(dataset, target=target)


def custom_type_matchup(
    dataset: TypeMatchupDataset,
    *,
    arg: str,
) -> TypeMatchup | None:
    name_to_type = {item.name: item for item in dataset.elements}
    type_names = _split_custom_type_names(arg, set(name_to_type))
    if type_names is None:
        return None
    elements = [name_to_type[name] for name in type_names]
    target = TypeCombinationSnapshot(
        id=-1,
        name=f"{''.join(item.name for item in elements)}（DIY 属性）",
        primary_id=elements[0].id,
        secondary_id=(elements[1].id if len(elements) == _MAX_CUSTOM_TYPES else None),
    )
    return build_type_matchup(dataset, target=target)


def build_type_matchup(
    dataset: TypeMatchupDataset,
    *,
    target: TypeCombinationSnapshot,
) -> TypeMatchup:
    table = {
        (source_id, target_id): value
        for source_id, target_id, value in dataset.relations
    }
    return TypeMatchup(
        target=target,
        attack_table=[
            (item, _calc_multiplier(table, target, item))
            for item in dataset.combinations
        ],
        defense_table=[
            (item, _calc_multiplier(table, item, target))
            for item in dataset.combinations
        ],
    )


def _lookup(table: RelationMap, atk_id: int, def_id: int) -> float:
    return table.get((atk_id, def_id), 1.0)


def _calc_mixed(c1: float, c2: float) -> float:
    total = c1 + c2
    if c1 == _SUPER_EFFECTIVE and c2 == _SUPER_EFFECTIVE:
        return total
    if _IMMUNE in (c1, c2):
        return total / 4
    return total / 2


def _double_attacks_single(
    table: RelationMap,
    atk_primary_id: int,
    atk_secondary_id: int,
    def_id: int,
) -> float:
    return _calc_mixed(
        _lookup(table, atk_primary_id, def_id),
        _lookup(table, atk_secondary_id, def_id),
    )


def _calc_multiplier(
    table: RelationMap,
    attacker: TypeCombinationSnapshot,
    defender: TypeCombinationSnapshot,
) -> float:
    atk_sec, def_sec = attacker.secondary_id, defender.secondary_id
    if atk_sec is None and def_sec is None:
        return _lookup(table, attacker.primary_id, defender.primary_id)
    if atk_sec is None and def_sec is not None:
        return _calc_mixed(
            _lookup(table, attacker.primary_id, defender.primary_id),
            _lookup(table, attacker.primary_id, def_sec),
        )
    if atk_sec is not None and def_sec is None:
        return _double_attacks_single(
            table,
            attacker.primary_id,
            atk_sec,
            defender.primary_id,
        )
    if atk_sec is None or def_sec is None:
        raise ValueError
    return (
        _double_attacks_single(table, attacker.primary_id, atk_sec, defender.primary_id)
        + _double_attacks_single(table, attacker.primary_id, atk_sec, def_sec)
    ) / 2


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
