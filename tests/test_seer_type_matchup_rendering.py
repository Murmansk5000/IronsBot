# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.seer_data.type_matchup_renderer import render_type_matchup
from ironsbot.services.seer.rendering.type_matchup import (
    TypeMatchupAssets,
    present_type_matchup,
)
from ironsbot.services.seer.type_calc import (
    ElementTypeSnapshot,
    TypeCombinationSnapshot,
    TypeMatchup,
    TypeMatchupDataset,
    custom_type_matchup,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


class _Images:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def fetch(self, kind: str, key: str, **_kwargs: object) -> bytes:
        assert _kwargs.get("fallback") is False
        self.requests.append((kind, key))
        return f"{kind}:{key}".encode()


def _combination(id_: int, name: str) -> TypeCombinationSnapshot:
    return TypeCombinationSnapshot(
        id=id_,
        name=name,
        primary_id=id_,
        secondary_id=None,
    )


def _matchup(*, custom: bool = False) -> TypeMatchup:
    target = (
        TypeCombinationSnapshot(-1, "草水", 1, 2) if custom else _combination(1, "草")
    )
    return TypeMatchup(
        target=target,
        attack_table=[(_combination(3, "火"), 2.0), (_combination(2, "水"), 0.5)],
        defense_table=[(_combination(4, "飞行"), 1.0)],
    )


def test_type_matchup_presentation_is_pure_and_orders_multipliers() -> None:
    document = present_type_matchup(
        _matchup(),
        TypeMatchupAssets(
            icons=((1, "target"), (2, "water"), (3, "fire"), (4, "fly")),
            target_icon="target",
            target_icon_secondary=None,
        ),
    )

    assert document.type_name == "草"
    assert [(item.name, item.multiplier) for item in document.attack_items] == [
        ("火", 2.0),
        ("水", 0.5),
    ]


@pytest.mark.asyncio
async def test_type_matchup_render_adapter_loads_custom_target_assets() -> None:
    images = _Images()
    captured: dict[str, Any] = {}

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"rendered"

    result = await render_type_matchup(
        cast("SeerImageSource", images),
        cast("HtmlTemplateRenderer", render_html),
        _matchup(custom=True),
    )

    assert result == b"rendered"
    assert images.requests == [
        ("element_type", "1"),
        ("element_type", "2"),
        ("element_type", "3"),
        ("element_type", "4"),
    ]
    assert captured["templates"]["type_icon_secondary"] is not None


@pytest.mark.asyncio
async def test_custom_type_presentation_preserves_order_and_separator_variants() -> (
    None
):
    dataset = TypeMatchupDataset(
        combinations=(_combination(1, "草"), _combination(2, "水")),
        elements=(ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")),
        relations=(),
    )
    images = _Images()
    calls: list[str] = []

    async def render_html(**kwargs: Any) -> bytes:
        title = str(kwargs["templates"]["type_name"])
        calls.append(title)
        return title.encode()

    for arg, title in (
        ("草+水", "草水（DIY 属性）"),
        ("水+草", "水草（DIY 属性）"),
        ("草／水", "草水（DIY 属性）"),
        ("水，草", "水草（DIY 属性）"),
    ):
        matchup = custom_type_matchup(dataset, arg=arg)
        assert matchup is not None
        result = await render_type_matchup(
            cast("SeerImageSource", images),
            cast("HtmlTemplateRenderer", render_html),
            matchup,
        )
        assert result == title.encode()
    assert calls == ["草水（DIY 属性）", "水草（DIY 属性）"] * 2
