# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.identities import IdentityConfig
from ironsbot.config.models.settings import QQOfficialAccountConfig, Settings
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.config.platform_references import (
    PlatformReferenceResolver,
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
    from collections.abc import Mapping

    from ironsbot.services.bilibili.preferences import BiliPushPreferenceStore
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository

EXPECTED_CROSS_PLATFORM_ENDPOINTS = 2


def _account(app_id: str) -> QQOfficialAccountConfig:
    return QQOfficialAccountConfig(app_id=app_id, secret="secret")


def _resolver(
    *,
    groups: Mapping[str, object] | None = None,
    users: Mapping[str, object] | None = None,
    accounts: Mapping[str, QQOfficialAccountConfig] | None = None,
) -> PlatformReferenceResolver:
    identities = IdentityConfig.model_validate(
        {"groups": groups or {}, "users": users or {}}
    )
    onebot = OneBotReferenceResolver(
        {
            alias: target.qq
            for alias, target in identities.groups.items()
            if target.qq is not None
        },
        {
            alias: target.qq
            for alias, target in identities.users.items()
            if target.qq is not None
        },
    )
    return build_platform_reference_resolver(
        onebot,
        identities,
        accounts or {"main": _account("app-a")},
    )


def test_platform_references_merge_cross_platform_group_identity() -> None:
    resolver = _resolver(
        groups={"same": {"qq": 123456, "official": {"main": "group-openid"}}}
    )

    assert resolver.group_conversation_refs("same", location="test.group") == (
        ConversationRef(Platform.ONEBOT, "group", "123456"),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "group-openid",
            account_id="app-a",
        ),
    )


def test_platform_references_merge_cross_platform_user_identity() -> None:
    resolver = _resolver(
        users={"same": {"qq": 234567, "official": {"main": "user-openid"}}}
    )

    assert resolver.actor_refs("same", location="test.user") == (
        ActorRef(Platform.ONEBOT, "234567"),
        ActorRef(Platform.QQ_OFFICIAL, "user-openid", account_id="app-a"),
    )


def test_platform_references_merge_identity_across_official_accounts() -> None:
    resolver = _resolver(
        groups={"same": {"official": {"first": "group-a", "second": "group-b"}}},
        accounts={"first": _account("app-a"), "second": _account("app-b")},
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


@pytest.mark.parametrize("kind", ["groups", "users"])
def test_identities_reject_duplicate_qq_targets(kind: str) -> None:
    with pytest.raises(ValueError, match="share QQ ID"):
        IdentityConfig.model_validate(
            {kind: {"first": {"qq": 123456}, "second": {"qq": 123456}}}
        )


@pytest.mark.parametrize("kind", ["groups", "users"])
def test_identities_reject_duplicate_official_targets(kind: str) -> None:
    with pytest.raises(ValueError, match="share an official endpoint"):
        IdentityConfig.model_validate(
            {
                kind: {
                    "first": {"official": {"main": "same-openid"}},
                    "second": {"official": {"main": "same-openid"}},
                }
            }
        )


def test_bilibili_targets_compile_every_identity_endpoint() -> None:
    config = BiliConfig.model_validate(
        {
            "accounts": {"example_account": {"uid": 912345678}},
            "push": {
                "groups": {"same_group": {"accounts": ["example_account"]}},
                "users": {"same_user": {"accounts": ["example_account"]}},
            },
        }
    )
    resolver = _resolver(
        groups={
            "same_group": {
                "qq": 123456,
                "official": {"main": "group-openid"},
            }
        },
        users={
            "same_user": {
                "qq": 234567,
                "official": {"main": "user-openid"},
            }
        },
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


def test_settings_accept_shared_identity_in_feature_policy() -> None:
    settings = Settings.model_validate(
        {
            "identities": {
                "groups": {
                    "same": {
                        "qq": 123456,
                        "official": {"example_bot": "group-openid"},
                    }
                },
                "users": {
                    "owner": {
                        "qq": 234567,
                        "official": {"example_bot": "user-openid"},
                    }
                },
            },
            "features": {
                "group_policy": {"same": ["seer_rank"]},
                "user_policy": {"owner": ["ai_chat"]},
            },
            "bot": {
                "qq_official": {
                    "accounts": {
                        "example_bot": {
                            "app_id": "app-a",
                            "secret": "secret",
                        }
                    }
                }
            },
        }
    )

    assert (
        len(
            settings.platform_references.group_conversation_refs(
                "same",
                location="test.group",
            )
        )
        == EXPECTED_CROSS_PLATFORM_ENDPOINTS
    )


def test_settings_reject_identity_for_undeclared_official_account() -> None:
    with pytest.raises(ValueError, match="undeclared official accounts: missing"):
        Settings.model_validate(
            {
                "identities": {
                    "groups": {"same": {"official": {"missing": "group-openid"}}}
                }
            }
        )


def test_removed_alias_tables_are_strictly_rejected() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        Settings.model_validate({"features": {"group_aliases": {"old": 123456}}})
