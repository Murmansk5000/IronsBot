# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM

from .countermark_stat_rank_models import (
    CountermarkStatRankCommand,
    CountermarkStatRankItem,
    StatSpec,
)
from .value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from seerapi_models import MintmarkORM
    from seerapi_models.common import SixAttributes

_MINTMARK_QUALITY_KEYS = ("Quality", "quality")


def collect_countermark_rank_items(
    mintmarks: list[MintmarkORM],
    command: CountermarkStatRankCommand,
    quality_map: dict[int, int],
) -> list[CountermarkStatRankItem]:
    if command.stat is None:
        return []

    result: list[CountermarkStatRankItem] = []
    for mintmark in mintmarks:
        class_name = _mintmark_class_name(mintmark)
        angle_count = _mintmark_angle_count(mintmark, quality_map)
        if command.angle_count is not None and angle_count != command.angle_count:
            continue

        attrs = _mark_attributes(mintmark)
        if attrs is None:
            continue

        value = _get_stat_value(attrs, command.stat)
        if value <= 0:
            continue

        result.append(
            CountermarkStatRankItem(
                mintmark=mintmark,
                attrs=attrs,
                value=value,
                total=float(attrs.total),
                class_name=class_name,
                angle_count=angle_count,
            )
        )

    return sorted(
        result,
        key=lambda item: (
            item.value,
            item.total,
            -item.mintmark.id,
        ),
        reverse=True,
    )


def _mark_attributes(mintmark: MintmarkORM) -> SixAttributes | None:
    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, AbilityPartORM):
        if part.max_attr_value is None:
            return None
        attr = part.max_attr_value.to_model()
    elif isinstance(part, UniversalPartORM):
        if part.max_attr_value is None:
            return None
        attr = part.max_attr_value.to_model()
        if part.extra_attr_value:
            attr = attr + part.extra_attr_value.to_model()
    elif isinstance(part, SkillPartORM):
        return None
    else:
        return None

    return attr.round()


def _mintmark_class_name(mintmark: MintmarkORM) -> str:
    part = mintmark.universal_part
    if not isinstance(part, UniversalPartORM) or part.mintmark_class is None:
        return ""

    return part.mintmark_class.name


def _object_quality(obj: object | None) -> int | None:
    if obj is None:
        return None

    for key in _MINTMARK_QUALITY_KEYS:
        quality = coerce_positive_int(getattr(obj, key, None))
        if quality is not None:
            return quality

    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        dumped = cast("Mapping[str, object]", model_dump())
        for key in _MINTMARK_QUALITY_KEYS:
            quality = coerce_positive_int(dumped.get(key))
            if quality is not None:
                return quality

    return None


def _configured_mintmark_quality(
    mintmark: MintmarkORM,
    quality_map: dict[int, int],
) -> int | None:
    return quality_map.get(mintmark.id)


def _mintmark_angle_count(
    mintmark: MintmarkORM,
    quality_map: dict[int, int],
) -> int | None:
    for quality in (
        _object_quality(mintmark),
        _object_quality(mintmark.ability_part),
        _object_quality(mintmark.skill_part),
        _object_quality(mintmark.universal_part),
        _configured_mintmark_quality(mintmark, quality_map),
    ):
        if quality is not None:
            return quality

    return None


def _get_stat_value(attrs: SixAttributes, stat: StatSpec) -> float:
    if stat.key == "total":
        return float(attrs.total)
    if stat.components:
        total = 0.0
        for component in stat.components:
            if component == "total":
                total += float(attrs.total)
            else:
                total += float(getattr(attrs, component))
        return total

    return float(getattr(attrs, stat.key))
