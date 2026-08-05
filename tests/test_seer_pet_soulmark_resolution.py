# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.integrations.seer_data.pet_soulmark_resolution import (
    resolve_partner_upgraded_soulmark_ids,
)
from ironsbot.services.seer.rendering.pet_info_models import (
    PetItemSnapshot,
    PetPartnerSnapshot,
    PetSoulmarkSnapshot,
)


def _soulmark(
    soulmark_id: int,
    description: str,
    *,
    intensified_to_id: int | None = None,
) -> PetSoulmarkSnapshot:
    return PetSoulmarkSnapshot(
        id=soulmark_id,
        desc=description,
        analyze_desc=None,
        formatting_adjustment=None,
        intensified=False,
        intensified_to_id=intensified_to_id,
        is_adv=False,
        pve_effective=None,
        tags=(),
    )


def _partner(before: str, after: str) -> PetPartnerSnapshot:
    return PetPartnerSnapshot(
        group_id=1,
        name="测试羁绊",
        cost_item=PetItemSnapshot(1, "契约徽章", 1),
        before_description=before,
        after_description=after,
        skill=None,
    )


def test_partner_resolution_prefers_published_soulmark_link() -> None:
    soulmarks = (
        _soulmark(10, "基础魂印", intensified_to_id=20),
        _soulmark(20, "强化魂印"),
    )

    result = resolve_partner_upgraded_soulmark_ids(
        soulmarks,
        _partner("错误的基础描述", "错误的强化描述"),
    )

    assert result == frozenset((20,))


def test_partner_resolution_uses_bounded_text_fallback_for_older_data() -> None:
    soulmarks = (_soulmark(10, "基础魂印"), _soulmark(20, "强化魂印"))

    result = resolve_partner_upgraded_soulmark_ids(
        soulmarks,
        _partner("基础魂印", "强化魂印"),
    )

    assert result == frozenset((20,))


def test_partner_resolution_returns_no_fact_without_a_reliable_match() -> None:
    result = resolve_partner_upgraded_soulmark_ids(
        (_soulmark(10, "基础魂印"), _soulmark(20, "强化魂印")),
        _partner("旧文本", "不存在的文本"),
    )

    assert result == frozenset()
