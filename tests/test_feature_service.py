import pytest
from pydantic import ValidationError

from ironsbot.config.models.settings import Settings
from ironsbot.core.features import (
    FEATURE_BUNDLES,
    FEATURE_KEYS,
    SEER_FEATURES,
    FeatureConfig,
    FeatureService,
)


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


def test_feature_service_blocks_configured_users_and_groups() -> None:
    feature_service = FeatureService(
        FeatureConfig(
            group_policy={"123": ["blacklist"]},
            user_policy={"456": ["blacklist"]},
        ),
        frozenset({456}),
    )

    assert feature_service.is_conversation_blocked(456)
    assert feature_service.is_conversation_blocked(999, 123)
    assert not feature_service.is_conversation_blocked(999, 321)


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


def test_feature_service_expands_configured_bundles() -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        bundles={
            "lite": ["seer_player", "seer_rank"],
            "standard": ["lite", "image", "bili_query"],
        },
        group_policy={"main": ["standard"]},
        superuser_bypass=False,
    )
    feature_service = FeatureService(feature_config, frozenset())

    assert feature_service.is_group_feature_allowed(999, 123, "seer_player")
    assert feature_service.is_group_feature_allowed(999, 123, "seer_rank")
    assert feature_service.is_group_feature_allowed(999, 123, "image")
    assert feature_service.is_group_feature_allowed(999, 123, "bili_query")
    assert not feature_service.is_group_feature_allowed(999, 123, "bili_push")


def test_message_action_features_are_registered_for_bundles_and_policies() -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        bundles={"custom_links": ["seerinfo_link"]},
        group_policy={"main": ["custom_links"]},
        superuser_bypass=False,
    )
    feature_service = FeatureService(
        feature_config,
        frozenset(),
        command_features=frozenset({"seerinfo_link"}),
    )

    assert feature_service.is_group_feature_allowed(
        999,
        123,
        "seerinfo_link",
    )


@pytest.mark.parametrize("bundle", ["all", "text", "message"])
def test_command_features_join_relevant_builtin_bundles(bundle: str) -> None:
    feature_service = FeatureService(
        FeatureConfig(
            group_policy={"123": [bundle]},
            superuser_bypass=False,
        ),
        frozenset(),
        command_features=frozenset({"custom_reply"}),
    )

    assert feature_service.is_group_feature_allowed(999, 123, "custom_reply")


@pytest.mark.parametrize("bundle", ["all", "text_push", "message"])
def test_schedule_features_join_relevant_builtin_bundles(bundle: str) -> None:
    feature_service = FeatureService(
        FeatureConfig(
            user_policy={"123": [bundle]},
            superuser_bypass=False,
        ),
        frozenset(),
        schedule_features=frozenset({"custom_reminder"}),
    )

    assert feature_service.is_private_feature_allowed(123, "custom_reminder")


def test_message_action_feature_cannot_reuse_bundle_name() -> None:
    with pytest.raises(
        ValueError,
        match="messaging action feature cannot use registered bundle",
    ):
        FeatureService(
            FeatureConfig(),
            frozenset(),
            command_features=frozenset({"query"}),
        )


def test_custom_bundle_cannot_replace_message_action_feature() -> None:
    with pytest.raises(
        ValueError,
        match="cannot replace registered feature",
    ):
        FeatureService(
            FeatureConfig(bundles={"custom_reply": ["text"]}),
            frozenset(),
            command_features=frozenset({"custom_reply"}),
        )


@pytest.mark.parametrize(
    ("bundles", "message"),
    [
        ({"seer": ["image"]}, "cannot replace registered feature"),
        ({"empty": []}, "features.bundles.empty must not be empty"),
        ({"all": [""]}, r"features.bundles.all\[0\] must not be empty"),
        ({"broken": ["missing"]}, r"features.bundles.broken\[0\]=missing"),
        ({"first": ["second"], "second": ["first"]}, "contains a cycle"),
        ({"management": ["admin_notice"]}, "must not include admin_notice"),
    ],
)
def test_invalid_configured_feature_bundles_are_rejected(
    bundles: dict[str, list[str]],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(features=FeatureConfig(bundles=bundles))


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
    assert feature_service.is_group_feature_allowed(
        999,
        123,
        "player_lineup_private",
    )
    assert not feature_service.is_group_feature_allowed(999, 123, "admin_notice")
    assert not feature_service.is_group_feature_allowed(999, 123, "blacklist")
    assert feature_service.groups_for_feature("seer_pet") == [123]
    assert feature_service.groups_for_feature("admin_notice") == []


def test_all_bundle_accepts_declared_custom_feature_but_not_blacklist() -> None:
    feature_service = FeatureService(
        FeatureConfig(
            bundles={"all": ["private_extension_action"]},
            group_policy={"123": ["all"]},
            superuser_bypass=False,
        ),
        frozenset(),
    )

    assert feature_service.is_group_feature_allowed(
        999,
        123,
        "private_extension_action",
    )
    assert not feature_service.is_group_feature_allowed(999, 123, "blacklist")


@pytest.mark.parametrize("feature", ["admin_notice", "blacklist"])
def test_all_bundle_rejects_protected_feature(feature: str) -> None:
    with pytest.raises(ValueError, match="must not include protected feature"):
        FeatureService(
            FeatureConfig(bundles={"all": [feature]}),
            frozenset(),
        )


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


def test_private_player_lineup_feature_is_in_all_bundle() -> None:
    assert "player_lineup_private" in FEATURE_KEYS
    assert "player_lineup_private" in FEATURE_BUNDLES["all"]


def test_private_lucky_skin_window_feature_is_in_all_bundle() -> None:
    assert "lucky_skin_window" in FEATURE_KEYS
    assert "lucky_skin_window" in FEATURE_BUNDLES["all"]
