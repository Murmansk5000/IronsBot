# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.settings import QQOfficialAccountConfig, Settings
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.config.platform_references import (
    PlatformReferenceError,
    build_platform_reference_resolver,
)
from ironsbot.core.bilibili import BiliConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.configured_targets.bilibili import (
    build_bili_configured_targets,
)
from ironsbot.services.bilibili.target_models import BiliConfiguredTargets
from ironsbot.services.bilibili.targets import BiliTargetService

if TYPE_CHECKING:
    from ironsbot.services.bilibili.preferences import BiliPushPreferenceStore
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )


def _account(
    app_id: str,
    *,
    group_aliases: dict[str, str] | None = None,
    user_aliases: dict[str, str] | None = None,
    group_member_aliases: dict[str, dict[str, str]] | None = None,
) -> QQOfficialAccountConfig:
    return QQOfficialAccountConfig(
        enabled=True,
        app_id=app_id,
        secret="secret",
        group_aliases=group_aliases or {},
        user_aliases=user_aliases or {},
        group_member_aliases=group_member_aliases or {},
    )


def test_platform_references_resolve_official_aliases_with_account_scope() -> None:
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver({}, {}),
        (
            _account(
                "app-a",
                group_aliases={"official_group": "group-openid"},
                user_aliases={"official_user": "user-openid"},
            ),
        ),
    )

    groups = resolver.group_conversation_refs(
        "official_group",
        location="test.group",
    )
    private = resolver.private_conversation_refs(
        "official_user",
        location="test.user",
    )

    assert groups == (
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-openid",
            account_id="app-a",
        ),
    )
    assert private == (
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            "user-openid",
            account_id="app-a",
        ),
    )


def test_platform_references_merge_cross_platform_group_aliases() -> None:
    onebot = OneBotReferenceResolver(
        {"same": 123456},
        {},
    )
    account = _account(
        "app-a",
        group_aliases={"same": "group-openid"},
    )

    resolver = build_platform_reference_resolver(onebot, (account,))

    assert resolver.group_conversation_refs("same", location="test.group") == (
        ConversationRef(Platform.ONEBOT, "group", "123456"),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-openid",
            account_id="app-a",
        ),
    )


def test_platform_references_merge_cross_platform_user_aliases() -> None:
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver({}, {"same": 234567}),
        (_account("app-a", user_aliases={"same": "user-openid"}),),
    )

    assert resolver.actor_refs("same", location="test.user") == (
        ActorRef(Platform.ONEBOT, "234567"),
        ActorRef(Platform.QQ_OFFICIAL, "user-openid", account_id="app-a"),
    )


def test_platform_references_merge_group_alias_across_official_accounts() -> None:
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver({}, {}),
        (
            _account("app-a", group_aliases={"same": "group-a"}),
            _account("app-b", group_aliases={"same": "group-b"}),
        ),
    )

    assert resolver.group_conversation_refs("same", location="test.group") == (
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-a",
            account_id="app-a",
        ),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-b",
            account_id="app-b",
        ),
    )


def test_platform_references_merge_user_alias_across_official_accounts() -> None:
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver({}, {}),
        (
            _account("app-a", user_aliases={"same": "user-a"}),
            _account("app-b", user_aliases={"same": "user-b"}),
        ),
    )

    assert resolver.actor_refs("same", location="test.user") == (
        ActorRef(Platform.QQ_OFFICIAL, "user-a", account_id="app-a"),
        ActorRef(Platform.QQ_OFFICIAL, "user-b", account_id="app-b"),
    )


def test_platform_references_keep_group_member_alias_scoped() -> None:
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver({}, {"owner": 234567}),
        (
            _account(
                "app-a",
                group_aliases={"admin": "group-openid"},
                group_member_aliases={
                    "admin": {
                        "owner": "member-openid",
                        "member_only": "member-only-openid",
                    },
                },
            ),
        ),
    )

    assert resolver.actor_refs("owner", location="test.user") == (
        ActorRef(Platform.ONEBOT, "234567"),
        ActorRef(
            Platform.QQ_OFFICIAL,
            "member-openid",
            "member",
            "group-openid",
            "app-a",
        ),
    )
    with pytest.raises(PlatformReferenceError, match="only group-scoped"):
        resolver.private_conversation_refs("member_only", location="test.private")


@pytest.mark.parametrize("kind", ["group_aliases", "user_aliases"])
def test_onebot_aliases_reject_duplicate_native_targets(kind: str) -> None:
    with pytest.raises(ValueError, match="must not map to the same target"):
        Settings.model_validate(
            {
                "features": {
                    kind: {
                        "first": 123456,
                        "second": 123456,
                    }
                }
            }
        )


@pytest.mark.parametrize("kind", ["group_aliases", "user_aliases"])
def test_official_aliases_reject_duplicate_scoped_targets(kind: str) -> None:
    with pytest.raises(ValueError, match="must not map to the same scoped target"):
        QQOfficialAccountConfig.model_validate(
            {
                "enabled": True,
                "app_id": "app-a",
                "secret": "secret",
                kind: {
                    "first": "same-openid",
                    "second": "same-openid",
                },
            }
        )


def test_official_member_aliases_reject_duplicate_scoped_targets() -> None:
    with pytest.raises(ValueError, match="must not map to the same scoped target"):
        _account(
            "app-a",
            group_aliases={"admin": "group-openid"},
            group_member_aliases={
                "admin": {"owner": "member-openid"},
                "group-openid": {"duplicate": "member-openid"},
            },
        )


def test_bilibili_targets_compile_official_aliases() -> None:
    config = BiliConfig.model_validate(
        {
            "accounts": {"example_account": {"uid": 912345678}},
            "push": {
                "groups": {
                    "official_group": {"accounts": ["example_account"]}
                },
                "users": {
                    "official_user": {"accounts": ["example_account"]}
                },
            },
        }
    )
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver({}, {}),
        (
            _account(
                "app-a",
                group_aliases={"official_group": "group-openid"},
                user_aliases={"official_user": "user-openid"},
            ),
        ),
    )

    targets = build_bili_configured_targets(config, resolver)

    group = next(iter(targets.group_rules))
    private = next(iter(targets.private_rules))
    assert (group.platform, group.account_id, group.id) == (
        Platform.QQ_OFFICIAL,
        "app-a",
        "group-openid",
    )
    assert (private.platform, private.account_id, private.id) == (
        Platform.QQ_OFFICIAL,
        "app-a",
        "user-openid",
    )


def test_bilibili_logical_aliases_compile_every_platform_endpoint() -> None:
    config = BiliConfig.model_validate(
        {
            "accounts": {"example_account": {"uid": 912345678}},
            "push": {
                "groups": {"same_group": {"accounts": ["example_account"]}},
                "users": {"same_user": {"accounts": ["example_account"]}},
            },
        }
    )
    resolver = build_platform_reference_resolver(
        OneBotReferenceResolver(
            {"same_group": 123456},
            {"same_user": 234567},
        ),
        (
            _account(
                "app-a",
                group_aliases={"same_group": "group-openid"},
                user_aliases={"same_user": "user-openid"},
            ),
        ),
    )

    targets = build_bili_configured_targets(config, resolver)

    assert set(targets.group_rules) == {
        ConversationRef(Platform.ONEBOT, "group", "123456"),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-openid",
            account_id="app-a",
        ),
    }
    assert set(targets.private_rules) == {
        ConversationRef(Platform.ONEBOT, "private", "234567"),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            "user-openid",
            account_id="app-a",
        ),
    }


def test_bilibili_private_history_permission_keeps_official_account_scope() -> None:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "same-openid",
        account_id="app-a",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id=actor.account_id,
    )
    service = BiliTargetService(
        BiliConfig(),
        FeatureService(
            group_features={},
            actor_features={actor: frozenset({"bili_query"})},
            superusers=frozenset(),
        ),
        BiliConfiguredTargets({}, {}),
        cast("BiliPushPreferenceStore", object()),
        cast("PushSubscriptionRepository", object()),
    )

    assert service.can_conversation_query_history(conversation)
    assert not service.can_conversation_query_history(
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            actor.id,
            account_id="app-b",
        )
    )


def test_settings_validate_official_bilibili_alias_target() -> None:
    settings = Settings.model_validate(
        {
            "bot": {
                "qq_official": {
                    "enabled": True,
                    "accounts": {
                        "example_bot": {
                            "enabled": True,
                            "app_id": "app-a",
                            "secret": "secret",
                            "group_aliases": {
                                "official_group": "group-openid"
                            },
                        }
                    },
                }
            },
            "bilibili": {
                "accounts": {"example_account": {"uid": 912345678}},
                "push": {
                    "groups": {
                        "official_group": {
                            "accounts": ["example_account"]
                        }
                    }
                },
            },
        }
    )

    target = next(
        iter(
            build_bili_configured_targets(
                settings.bilibili,
                settings.platform_references,
            ).group_rules
        )
    )
    assert (target.platform, target.account_id, target.id) == (
        Platform.QQ_OFFICIAL,
        "app-a",
        "group-openid",
    )


def test_settings_accept_cross_platform_logical_group_alias() -> None:
    settings = Settings.model_validate(
        {
            "features": {
                "group_aliases": {"same": 123456},
                "user_aliases": {"owner": 234567},
                "group_policy": {"same": ["seer_rank"]},
                "user_policy": {"owner": ["ai_chat"]},
            },
            "bot": {
                "qq_official": {
                    "enabled": True,
                    "accounts": {
                        "example_bot": {
                            "enabled": True,
                            "app_id": "app-a",
                            "secret": "secret",
                            "group_aliases": {"same": "group-openid"},
                            "user_aliases": {"owner": "user-openid"},
                            "group_member_aliases": {
                                "same": {"operator": "member-openid"}
                            },
                        }
                    },
                }
            },
        }
    )

    assert settings.platform_references.group_conversation_refs(
        "same",
        location="test.group",
    ) == (
        ConversationRef(Platform.ONEBOT, "group", "123456"),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-openid",
            account_id="app-a",
        ),
    )


def test_settings_accept_official_only_alias_in_shared_feature_policy() -> None:
    settings = Settings.model_validate(
        {
            "features": {
                "group_policy": {"official_only": ["seer_rank"]},
                "user_policy": {"official_user": ["ai_chat"]},
            },
            "bot": {
                "qq_official": {
                    "enabled": True,
                    "accounts": {
                        "example_bot": {
                            "enabled": True,
                            "app_id": "app-a",
                            "secret": "secret",
                            "group_aliases": {
                                "official_only": "group-openid"
                            },
                            "user_aliases": {
                                "official_user": "user-openid"
                            },
                        }
                    },
                }
            },
        }
    )

    assert settings.features.group_policy == {"official_only": ["seer_rank"]}
    assert settings.features.user_policy == {"official_user": ["ai_chat"]}
