import pytest
from pydantic import ValidationError

from ironsbot.config.models.features import (
    FEATURE_BUNDLES,
    FeatureConfig,
    build_feature_service,
)
from ironsbot.config.models.settings import Settings
from ironsbot.core.features import (
    FEATURE_KEYS,
    SEER_FEATURES,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform

_ACTOR = ActorRef(Platform.ONEBOT, "999")


def _actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _group(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _private(user_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "private", str(user_id))


def test_feature_service_reads_feature_config() -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        user_aliases={"owner": 456},
        group_policy={"main": ["seer"]},
        user_policy={"owner": ["ai_chat"]},
        superuser_bypass=False,
    )
    feature_service = build_feature_service(feature_config, frozenset())

    assert feature_service.conversations_for_feature("seer_pet") == [_group(123)]
    assert feature_service.actors_for_feature("ai_chat") == [_actor(456)]
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "seer_pet")
    assert not feature_service.is_feature_allowed(_ACTOR, _group(123), "text")


def test_user_policy_applies_to_the_same_actor_in_group_chat() -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            user_aliases={"owner": 456},
            user_policy={"owner": ["ai_chat"]},
        ),
        (),
    )

    assert feature_service.is_feature_allowed(_actor(456), _group(123), "ai_chat")
    assert not feature_service.is_feature_allowed(_actor(789), _group(123), "ai_chat")


def test_feature_service_exposes_only_explicitly_configured_feature_keys() -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            group_policy={"123": ["seer_player"]},
            user_policy={"456": ["ai_chat"]},
            superuser_bypass=True,
        ),
        frozenset({789}),
    )

    assert feature_service.configured_feature_keys == frozenset(
        {"seer_player", "ai_chat"}
    )


def test_platform_feature_references_do_not_cross_platforms() -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            group_policy={"123": ["seer"]},
            user_policy={"456": ["ai_chat"]},
            superuser_bypass=True,
        ),
        frozenset({456}),
    )
    onebot_actor = ActorRef(Platform.ONEBOT, "456")
    onebot_group = ConversationRef(Platform.ONEBOT, "group", "123")
    official_actor = ActorRef(Platform.QQ_OFFICIAL, "456")
    official_group = ConversationRef(Platform.QQ_OFFICIAL, "group", "123")

    assert feature_service.actor_has_feature(onebot_actor, "ai_chat")
    assert feature_service.conversation_has_feature(onebot_group, "seer_pet")
    assert feature_service.is_feature_allowed(onebot_actor, onebot_group, "seer_pet")
    assert not feature_service.actor_has_feature(official_actor, "ai_chat")
    assert not feature_service.conversation_has_feature(official_group, "seer_pet")
    assert not feature_service.is_feature_allowed(
        official_actor,
        official_group,
        "seer_pet",
    )


def test_actor_feature_policy_applies_superuser_bypass_without_onebot_ids() -> None:
    feature_service = build_feature_service(
        FeatureConfig(superuser_bypass=True),
        frozenset({456}),
    )

    assert feature_service.is_actor_feature_allowed(
        ActorRef(Platform.ONEBOT, "456"),
        "team_resource_subscription",
    )
    assert not feature_service.is_actor_feature_allowed(
        ActorRef(Platform.QQ_OFFICIAL, "456"),
        "team_resource_subscription",
    )


def test_feature_service_blocks_configured_users_and_groups() -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            group_policy={"123": ["blacklist"]},
            user_policy={"456": ["blacklist"]},
        ),
        frozenset({456}),
    )

    assert feature_service.is_message_blocked(
        ActorRef(Platform.ONEBOT, "456"),
        ConversationRef(Platform.ONEBOT, "private", "456"),
    )
    assert feature_service.is_message_blocked(
        ActorRef(Platform.ONEBOT, "999"),
        ConversationRef(Platform.ONEBOT, "group", "123"),
    )
    assert not feature_service.is_message_blocked(
        ActorRef(Platform.ONEBOT, "999"),
        ConversationRef(Platform.ONEBOT, "group", "321"),
    )


def test_feature_service_reads_query_bundle() -> None:
    assert "query" in FEATURE_BUNDLES
    assert "custom" not in FEATURE_BUNDLES

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["query"]},
        superuser_bypass=False,
    )
    feature_service = build_feature_service(feature_config, frozenset())

    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "seer_pet")
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "seer_rank")
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "bili_query")
    assert feature_service.is_feature_allowed(
        _ACTOR,
        _group(123),
        "seer_activity_query",
    )
    assert not feature_service.is_feature_allowed(_ACTOR, _group(123), "text")


def test_seer_activity_is_the_only_activity_feature_bundle() -> None:
    assert "seer_activity" in FEATURE_BUNDLES
    assert "activity" not in FEATURE_BUNDLES
    assert FEATURE_BUNDLES["seer_activity"] == frozenset(
        {"seer_activity_query", "seer_activity_push"},
    )


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
    feature_service = build_feature_service(feature_config, frozenset())

    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "seer_player")
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "seer_rank")
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "image")
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "bili_query")
    assert not feature_service.is_feature_allowed(_ACTOR, _group(123), "bili_push")


def test_message_action_features_are_registered_for_bundles_and_policies() -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        bundles={"custom_links": ["seerinfo_link"]},
        group_policy={"main": ["custom_links"]},
        superuser_bypass=False,
    )
    feature_service = build_feature_service(
        feature_config,
        frozenset(),
        command_features=frozenset({"seerinfo_link"}),
    )

    assert feature_service.is_feature_allowed(
        _ACTOR,
        _group(123),
        "seerinfo_link",
    )


@pytest.mark.parametrize("bundle", ["all", "text", "message"])
def test_command_features_join_relevant_builtin_bundles(bundle: str) -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            group_policy={"123": [bundle]},
            superuser_bypass=False,
        ),
        frozenset(),
        command_features=frozenset({"custom_reply"}),
    )

    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "custom_reply")


@pytest.mark.parametrize("bundle", ["all", "text_push", "message"])
def test_schedule_features_join_relevant_builtin_bundles(bundle: str) -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            user_policy={"123": [bundle]},
            superuser_bypass=False,
        ),
        frozenset(),
        schedule_features=frozenset({"custom_reminder"}),
    )

    assert feature_service.is_feature_allowed(
        _actor(123),
        _private(123),
        "custom_reminder",
    )


def test_message_action_feature_cannot_reuse_bundle_name() -> None:
    with pytest.raises(
        ValueError,
        match="messaging action feature cannot use registered bundle",
    ):
        build_feature_service(
            FeatureConfig(),
            frozenset(),
            command_features=frozenset({"query"}),
        )


def test_custom_bundle_cannot_replace_message_action_feature() -> None:
    with pytest.raises(
        ValueError,
        match="cannot replace registered feature",
    ):
        build_feature_service(
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
    feature_service = build_feature_service(feature_config, frozenset())

    for feature in SEER_FEATURES:
        assert feature_service.is_feature_allowed(_ACTOR, _group(123), feature)


def test_all_feature_bundle_does_not_include_admin_notice() -> None:
    assert "all" in FEATURE_BUNDLES
    assert "admin_notice" not in FEATURE_BUNDLES["all"]

    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        group_policy={"main": ["all"]},
        superuser_bypass=False,
    )
    feature_service = build_feature_service(feature_config, frozenset())

    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "seer_pet")
    assert feature_service.is_feature_allowed(_ACTOR, _group(123), "fire_manual_ad")
    assert feature_service.is_feature_allowed(
        _ACTOR,
        _group(123),
        "player_lineup_private",
    )
    assert not feature_service.is_feature_allowed(_ACTOR, _group(123), "admin_notice")
    assert not feature_service.is_feature_allowed(_ACTOR, _group(123), "blacklist")
    assert feature_service.conversations_for_feature("seer_pet") == [_group(123)]
    assert feature_service.conversations_for_feature("admin_notice") == []


def test_all_bundle_accepts_declared_custom_feature_but_not_blacklist() -> None:
    feature_service = build_feature_service(
        FeatureConfig(
            bundles={"all": ["private_extension_action"]},
            group_policy={"123": ["all"]},
            superuser_bypass=False,
        ),
        frozenset(),
    )

    assert feature_service.is_feature_allowed(
        _ACTOR,
        _group(123),
        "private_extension_action",
    )
    assert not feature_service.is_feature_allowed(_ACTOR, _group(123), "blacklist")


@pytest.mark.parametrize("feature", ["admin_notice", "blacklist"])
def test_all_bundle_rejects_protected_feature(feature: str) -> None:
    with pytest.raises(ValueError, match="must not include protected feature"):
        build_feature_service(
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


def test_lucky_skin_window_feature_is_in_all_bundle() -> None:
    assert "lucky_skin_window" in FEATURE_KEYS
    assert "lucky_skin_window" in FEATURE_BUNDLES["all"]
