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
) -> QQOfficialAccountConfig:
    return QQOfficialAccountConfig(
        enabled=True,
        app_id=app_id,
        secret="secret",
        group_aliases=group_aliases or {},
        user_aliases=user_aliases or {},
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

    group = resolver.group_conversation_ref(
        "official_group",
        location="test.group",
    )
    private = resolver.private_conversation_ref(
        "official_user",
        location="test.user",
    )

    assert group.platform is Platform.QQ_OFFICIAL
    assert group.kind == "group"
    assert group.id == "group-openid"
    assert group.account_id == "app-a"
    assert private.platform is Platform.QQ_OFFICIAL
    assert private.kind == "private"
    assert private.id == "user-openid"
    assert private.account_id == "app-a"


@pytest.mark.parametrize("kind", ["group", "user"])
def test_platform_references_reject_cross_platform_alias_collisions(
    kind: str,
) -> None:
    onebot = OneBotReferenceResolver(
        {"same": 123456} if kind == "group" else {},
        {"same": 234567} if kind == "user" else {},
    )
    account = _account(
        "app-a",
        group_aliases={"same": "group-openid"} if kind == "group" else {},
        user_aliases={"same": "user-openid"} if kind == "user" else {},
    )

    with pytest.raises(
        PlatformReferenceError,
        match=f"configured {kind} alias is not globally unique: same",
    ):
        build_platform_reference_resolver(onebot, (account,))


def test_platform_references_reject_alias_reused_by_official_accounts() -> None:
    with pytest.raises(PlatformReferenceError, match="not globally unique"):
        build_platform_reference_resolver(
            OneBotReferenceResolver({}, {}),
            (
                _account(
                    "app-a",
                    group_aliases={"same": "group-a"},
                ),
                _account(
                    "app-b",
                    group_aliases={"same": "group-b"},
                ),
            ),
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


def test_settings_reject_cross_platform_target_alias_collision() -> None:
    with pytest.raises(ValueError, match="group alias is not globally unique"):
        Settings.model_validate(
            {
                "features": {"group_aliases": {"same": 123456}},
                "bot": {
                    "qq_official": {
                        "enabled": True,
                        "accounts": {
                            "example_bot": {
                                "enabled": True,
                                "app_id": "app-a",
                                "secret": "secret",
                                "group_aliases": {"same": "group-openid"},
                            }
                        },
                    }
                },
            }
        )
