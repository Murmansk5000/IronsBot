from pytest import MonkeyPatch

from ironsbot.config.models.feature import FEATURE_ALIASES, SEER_FEATURES, FeatureConfig
from ironsbot.shared.features import service
from ironsbot.shared.features.registry import features_for_module
from tests.helpers.config import stub_app_config


def test_feature_service_reads_app_config_feature(
    monkeypatch: MonkeyPatch,
) -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        user_aliases={"owner": 456},
        group_policy={"main": ["seer"]},
        user_policy={"owner": ["ai_chat"]},
        superuser_bypass=False,
    )
    monkeypatch.setattr(
        service,
        "get_app_config",
        lambda: stub_app_config(feature_config=feature_config),
    )

    feature_service = service.FeatureService()

    assert feature_service.groups_for_feature("seer") == [123]
    assert feature_service.users_for_feature("ai_chat") == [456]
    assert set(feature_service.resolve_group_policy(123)) == SEER_FEATURES
    assert feature_service.resolve_user_policy(456) == ["ai_chat"]
    assert feature_service.is_group_feature_allowed(999, 123, "seer_pet")
    assert not feature_service.is_group_feature_allowed(999, 123, "text")


def test_feature_service_reads_query_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    assert "query" in FEATURE_ALIASES
    assert "custom" not in FEATURE_ALIASES

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["query"]},
        superuser_bypass=False,
    )
    monkeypatch.setattr(
        service,
        "get_app_config",
        lambda: stub_app_config(feature_config=feature_config),
    )

    feature_service = service.FeatureService()

    assert feature_service.is_group_feature_allowed(999, 123, "seer_pet")
    assert feature_service.is_group_feature_allowed(999, 123, "bili_query")
    assert feature_service.is_group_feature_allowed(999, 123, "seer_activity_query")
    assert not feature_service.is_group_feature_allowed(999, 123, "text")


def test_seer_alias_enables_all_seer_subfeatures(
    monkeypatch: MonkeyPatch,
) -> None:
    assert FEATURE_ALIASES["seer"] == SEER_FEATURES

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["seer"]},
        superuser_bypass=False,
    )
    monkeypatch.setattr(
        service,
        "get_app_config",
        lambda: stub_app_config(feature_config=feature_config),
    )

    feature_service = service.FeatureService()

    for feature in SEER_FEATURES:
        assert feature_service.is_group_feature_allowed(999, 123, feature)


def test_rank_alias_enables_seer_rank(
    monkeypatch: MonkeyPatch,
) -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["rank"]},
        superuser_bypass=False,
    )
    monkeypatch.setattr(
        service,
        "get_app_config",
        lambda: stub_app_config(feature_config=feature_config),
    )

    feature_service = service.FeatureService()

    assert feature_service.is_group_feature_allowed(999, 123, "rank")
    assert feature_service.is_group_feature_allowed(999, 123, "seer_rank")
    assert not feature_service.is_group_feature_allowed(999, 123, "seer_pet")


def test_all_feature_alias_does_not_include_admin_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    assert "all" in FEATURE_ALIASES
    assert "admin_notice" not in FEATURE_ALIASES["all"]

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["all"]},
        superuser_bypass=False,
    )
    monkeypatch.setattr(
        service,
        "get_app_config",
        lambda: stub_app_config(feature_config=feature_config),
    )

    feature_service = service.FeatureService()

    assert feature_service.is_group_feature_allowed(999, 123, "seer_pet")
    assert feature_service.is_group_feature_allowed(999, 123, "fire_manual_ad")
    assert not feature_service.is_group_feature_allowed(999, 123, "admin_notice")
    assert feature_service.groups_for_feature("seer_pet") == [123]
    assert feature_service.groups_for_feature("admin_notice") == []


def test_team_audit_feature_is_registered() -> None:
    assert "team_audit" in FEATURE_ALIASES["message"]
    assert features_for_module("ironsbot.plugins.team_audit_welcome") == (
        "team_audit",
    )


def test_team_resource_feature_is_registered() -> None:
    assert "team_resource_subscription" in FEATURE_ALIASES["message"]
    assert "team_resource_subscription" in FEATURE_ALIASES["all"]
    assert features_for_module("ironsbot.plugins.team_resource_subscription") == (
        "team_resource_subscription",
    )


def test_fire_manual_feature_is_registered() -> None:
    assert "fire_manual_ad" in FEATURE_ALIASES["all"]
    assert features_for_module("ironsbot.plugins.fire_manual_ad") == ("fire_manual_ad",)
