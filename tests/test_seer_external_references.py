from __future__ import annotations

import pytest
from pydantic import ValidationError

from ironsbot.config.models.seer import ExternalReferencesConfig
from ironsbot.config.models.settings import Settings
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
    peak_rank_reference,
)


def test_all_reference_urls_are_available_by_default() -> None:
    references = SeerInfoReferences(ExternalReferencesConfig())

    expected = {
        SeerInfoReference.PLAYER_QUERY: "/query",
        SeerInfoReference.TEAM_QUERY: "/query",
        SeerInfoReference.SERVER_STATUS: "/query",
        SeerInfoReference.WEEKLY_PREVIEW: "/preview",
        SeerInfoReference.BILIBILI_HISTORY: "/bilibili",
        SeerInfoReference.PEAK_POOL: "/peak/pvpban",
        SeerInfoReference.PEAK_MASTER_POOL: "/peak/pvpcostmode",
        SeerInfoReference.PEAK_VOTE: "/peak/pvpvote",
    }
    for reference, suffix in expected.items():
        assert references.url_for(reference).endswith(suffix)


@pytest.mark.parametrize(
    ("peak_type", "category", "suffix"),
    (
        (1, "player", "/peak/pvprank/sports/player"),
        (2, "suit", "/peak/pvprank/wild/suit"),
        (3, "title", "/peak/pvprank/expert/title"),
        (1, "pet", "/peak/pvprank/sports/monster"),
        (2, "pet", "/peak/pvprank/wild/monster"),
        (3, "pet", "/peak/pvprank/expert/monster"),
    ),
)
def test_peak_references_follow_mode_and_category(
    peak_type: int,
    category: str,
    suffix: str,
) -> None:
    references = SeerInfoReferences(ExternalReferencesConfig())

    reference = peak_rank_reference(peak_type=peak_type, category=category)

    assert references.url_for(reference).endswith(suffix)


def test_category_toggle_hides_all_matching_peak_links() -> None:
    references = SeerInfoReferences(ExternalReferencesConfig(peak_suit_rank=False))

    assert not references.url_for(
        peak_rank_reference(peak_type=1, category="suit")
    )
    assert not references.url_for(
        peak_rank_reference(peak_type=2, category="suit")
    )
    assert references.url_for(
        peak_rank_reference(peak_type=3, category="title")
    )


def test_append_adds_reference_only_when_enabled() -> None:
    enabled = SeerInfoReferences(ExternalReferencesConfig())
    disabled = SeerInfoReferences(ExternalReferencesConfig(player_query=False))

    assert "相关查询：https://seerinfo.yuyuqaq.cn/query" in enabled.append(
        "查询结果", SeerInfoReference.PLAYER_QUERY
    )
    assert disabled.append("查询结果", SeerInfoReference.PLAYER_QUERY) == "查询结果"


def test_reference_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unknown"):
        ExternalReferencesConfig.model_validate({"unknown": True})


def test_settings_rejects_unknown_reference_keys_even_when_other_extras_ignore(
) -> None:
    with pytest.raises(ValidationError, match="external_references"):
        Settings.model_validate(
            {"seer": {"external_references": {"unknown": True}}},
            extra="ignore",
        )


@pytest.mark.parametrize("value", ("true", 1, 0))
def test_reference_toggles_require_real_toml_booleans(value: object) -> None:
    with pytest.raises(ValidationError):
        ExternalReferencesConfig.model_validate({"player_query": value})
