# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ironsbot.services.seer.rendering.cache_key import (
    render_document_cache_key,
    render_request_cache_key,
)
from ironsbot.services.seer.rendering.type_matchup import (
    TypeMatchupAssets,
    present_type_matchup,
)
from ironsbot.services.seer.type_calc import TypeCombinationSnapshot, TypeMatchup


def test_render_document_cache_key_includes_loaded_asset_content() -> None:
    target = TypeCombinationSnapshot(1, "草", 1, None)
    water = TypeCombinationSnapshot(2, "水", 2, None)
    matchup = TypeMatchup(target, [(water, 2.0)], [])

    original = present_type_matchup(
        matchup,
        TypeMatchupAssets(
            icons=((1, "data:image/png;base64,b2xk"), (2, "water")),
            target_icon="data:image/png;base64,b2xk",
            target_icon_secondary=None,
        ),
    )
    changed_asset = present_type_matchup(
        matchup,
        TypeMatchupAssets(
            icons=((1, "data:image/png;base64,bmV3"), (2, "water")),
            target_icon="data:image/png;base64,bmV3",
            target_icon_secondary=None,
        ),
    )

    assert render_document_cache_key(original) == render_document_cache_key(original)
    assert render_document_cache_key(original) != render_document_cache_key(
        changed_asset
    )


def test_render_document_cache_key_includes_renderer_fingerprint() -> None:
    target = TypeCombinationSnapshot(1, "草", 1, None)
    matchup = TypeMatchup(target, [], [])
    document = present_type_matchup(
        matchup,
        TypeMatchupAssets(
            icons=((1, "target"),),
            target_icon="target",
            target_icon_secondary=None,
        ),
    )

    assert render_document_cache_key(
        document,
        renderer_fingerprint="template-v1",
    ) != render_document_cache_key(
        document,
        renderer_fingerprint="template-v2",
    )


def test_render_request_cache_key_is_stable_for_equivalent_mapping_order() -> None:
    assert render_request_cache_key(
        "test",
        {"left": (1, 2), "right": {"value": "x"}},
    ) == render_request_cache_key(
        "test",
        {"right": {"value": "x"}, "left": (1, 2)},
    )
