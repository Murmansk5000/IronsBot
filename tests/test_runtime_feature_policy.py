# SPDX-License-Identifier: MIT
import pytest

from ironsbot.core.command_catalog import CommandContext, feature_is_visible
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform

_FEATURE = "player_lineup_private"


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("is_group", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("blocked", [True, False])
def test_help_visibility_respects_scope_and_blacklist(
    platform: Platform, *, is_group: bool, enabled: bool, blocked: bool
) -> None:
    account = "test-account" if platform is Platform.QQ_OFFICIAL else None
    actor = ActorRef(platform, "test-user", account_id=account)
    conversation = ConversationRef(
        platform,
        "group" if is_group else "private",
        "test-group" if is_group else actor.id,
        account_id=account,
    )
    configured = frozenset({_FEATURE}) if enabled else frozenset()
    features = FeatureService(
        {conversation: configured} if is_group else {},
        {actor: configured | ({"blacklist"} if blocked else set())},
        frozenset(),
    )

    context = CommandContext(actor, conversation)
    visible = feature_is_visible(features, context, _FEATURE)
    assert visible is (enabled and not blocked)


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("bypass", [True, False])
def test_superuser_execution_bypass_does_not_expand_group_help(
    platform: Platform, *, bypass: bool
) -> None:
    account = "test-account" if platform is Platform.QQ_OFFICIAL else None
    actor = ActorRef(platform, "test-user", account_id=account)
    conversation = ConversationRef(platform, "group", "test-group", account_id=account)
    features = FeatureService({}, {}, frozenset({actor}), superuser_bypass=bypass)

    assert features.is_feature_allowed(actor, conversation, _FEATURE) is bypass
    context = CommandContext(actor, conversation)
    assert not feature_is_visible(features, context, _FEATURE)


@pytest.mark.parametrize("platform", list(Platform))
def test_group_blacklist_overrides_configured_help(platform: Platform) -> None:
    account = "test-account" if platform is Platform.QQ_OFFICIAL else None
    actor = ActorRef(platform, "test-user", account_id=account)
    conversation = ConversationRef(platform, "group", "test-group", account_id=account)
    features = FeatureService(
        {conversation: frozenset({_FEATURE, "blacklist"})}, {}, frozenset({actor})
    )

    context = CommandContext(actor, conversation)
    assert not feature_is_visible(features, context, _FEATURE)
