import pytest
from pydantic import ValidationError

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.core.features import (
    FEATURE_BUNDLES,
    FEATURE_KEYS,
    SEER_FEATURES,
)
from ironsbot.shared.features import FeatureService


def test_feature_service_reads_feature_config() -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        user_aliases={"owner": 456},
        group_policy={"main": ["seer"]},
        user_policy={"owner": ["ai_chat"]},
        superuser_bypass=False,
    )
    feature_service = FeatureService(feature_config, frozenset())

    assert feature_service.groups_for_feature("seer") == [123]
    assert feature_service.users_for_feature("ai_chat") == [456]
    assert feature_service.is_group_feature_allowed(999, 123, "seer_pet")
    assert not feature_service.is_group_feature_allowed(999, 123, "text")


def test_feature_service_reads_query_bundle() -> None:
    assert "query" in FEATURE_BUNDLES
    assert "custom" not in FEATURE_BUNDLES

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["query"]},
        superuser_bypass=False,
    )
    feature_service = FeatureService(feature_config, frozenset())

    assert feature_service.is_group_feature_allowed(999, 123, "seer_pet")
    assert feature_service.is_group_feature_allowed(999, 123, "seer_rank")
    assert feature_service.is_group_feature_allowed(999, 123, "bili_query")
    assert feature_service.is_group_feature_allowed(999, 123, "seer_activity_query")
    assert not feature_service.is_group_feature_allowed(999, 123, "text")


def test_seer_bundle_enables_all_seer_subfeatures() -> None:
    assert FEATURE_BUNDLES["seer"] == SEER_FEATURES

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["seer"]},
        superuser_bypass=False,
    )
    feature_service = FeatureService(feature_config, frozenset())

    for feature in SEER_FEATURES:
        assert feature_service.is_group_feature_allowed(999, 123, feature)


def test_removed_rank_feature_is_rejected() -> None:
    assert "rank" not in FEATURE_KEYS
    assert "rank" not in FEATURE_BUNDLES

    with pytest.raises(
        ValidationError,
        match=r"feature.group_policy.main\[0\]=rank",
    ):
        FeatureConfig(group_policy={"main": ["rank"]})


def test_all_feature_bundle_does_not_include_admin_notice() -> None:
    assert "all" in FEATURE_BUNDLES
    assert "admin_notice" not in FEATURE_BUNDLES["all"]

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["all"]},
        superuser_bypass=False,
    )
    feature_service = FeatureService(feature_config, frozenset())

    assert feature_service.is_group_feature_allowed(999, 123, "seer_pet")
    assert feature_service.is_group_feature_allowed(999, 123, "fire_manual_ad")
    assert not feature_service.is_group_feature_allowed(999, 123, "admin_notice")
    assert feature_service.groups_for_feature("seer_pet") == [123]
    assert feature_service.groups_for_feature("admin_notice") == []


def test_team_audit_feature_is_registered() -> None:
    assert "team_audit" in FEATURE_BUNDLES["message"]


def test_team_resource_feature_is_registered() -> None:
    assert "team_resource_subscription" in FEATURE_BUNDLES["message"]
    assert "team_resource_subscription" in FEATURE_BUNDLES["all"]


def test_fire_manual_feature_is_registered() -> None:
    assert "fire_manual_ad" in FEATURE_BUNDLES["all"]
    assert "ai_intent_fire_manual" in FEATURE_BUNDLES["all"]


def test_team_recommend_feature_is_registered() -> None:
    assert "ai_intent_team_recommend" in FEATURE_BUNDLES["all"]
