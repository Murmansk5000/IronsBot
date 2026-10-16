# SPDX-License-Identifier: MIT
from dataclasses import replace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from ironsbot.config.models.settings import BotConfig
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.push_routing import PushRouteDecision
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
from tests.test_proactive_delivery import PRIVATE, FakeOfficialMessenger, _delivery


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("has_address", [False, True])
@pytest.mark.asyncio
async def test_unconfigured_private_route_follows_shared_switch(
    *,
    enabled: bool,
    has_address: bool,
) -> None:
    routes = PrivateConversationRoutes(
        onebot_enabled=False,
        default_account="app1",
        official_accounts=frozenset({"app1"}),
        use_default_for_unconfigured_targets=enabled,
    )
    if has_address:
        routes.register(
            CrossPlatformIdentityLink(
                PRIVATE.id, OfficialIdentity("app1", "user", "test-openid"), 1
            )
        )
    notices = AsyncMock()
    delivery, messenger, _ = _delivery(
        messenger=FakeOfficialMessenger(), private_routes=routes
    )
    delivery = replace(delivery, private_failure_notice=notices)
    result = await delivery.send(
        OutboundMessage.from_text("test"), (PRIVATE,), action_name="scheduled"
    )
    if not enabled:
        assert result.skipped == (PRIVATE,)
        assert not result.failed and not result.results
        assert not messenger.calls
        notices.assert_not_awaited()
    elif has_address:
        assert len(result.succeeded) == 1
        notices.assert_not_awaited()
    else:
        assert result.failed == (PRIVATE,)
        notices.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_missing_route_still_reports_without_default_fallback() -> None:
    routes = PrivateConversationRoutes(
        onebot_enabled=False,
        default_account="app2",
        official_accounts=frozenset({"app1", "app2"}),
        preferred_accounts={PRIVATE.id: "app1"},
    )
    routes.register(
        CrossPlatformIdentityLink(
            PRIVATE.id, OfficialIdentity("app2", "user", "other-openid"), 1
        )
    )
    notices = AsyncMock()
    delivery, messenger, _ = _delivery(
        messenger=FakeOfficialMessenger(), private_routes=routes
    )
    delivery = replace(delivery, private_failure_notice=notices)
    result = await delivery.send(
        OutboundMessage.from_text("test"), (PRIVATE,), action_name="scheduled"
    )
    assert result.failed == (PRIVATE,)
    assert not result.skipped
    assert not messenger.calls
    notices.assert_awaited_once()


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_unconfigured_linked_endpoint_cannot_bypass_policy(platform: Platform) -> None:
    routes = PrivateConversationRoutes(
        onebot_enabled=False,
        official_accounts=frozenset({"app1"}),
        default_account="app1",
    )
    routes.register(
        CrossPlatformIdentityLink(
            PRIVATE.id, OfficialIdentity("app1", "user", "test-openid"), 1
        )
    )
    target = (
        PRIVATE
        if platform is Platform.ONEBOT
        else ConversationRef(platform, "private", "test-openid", account_id="app1")
    )
    assert routes.selected_for(target) is None
    assert routes.decision_for(target).status == "skipped"


@pytest.mark.asyncio
async def test_unconfigured_group_is_skipped_not_failed() -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "20001")
    routes = PrivateConversationRoutes(
        group_route=lambda value: PushRouteDecision(
            "skipped", value, "unconfigured_target"
        )
    )
    delivery, messenger, _ = _delivery(private_routes=routes)
    result = await delivery.send(
        OutboundMessage.from_text("test"), (target,), action_name="scheduled"
    )
    assert result.skipped == (target,)
    assert not result.failed
    assert not messenger.calls


def test_old_group_only_config_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        BotConfig.model_validate({"use_default_for_unconfigured_groups": False})


@pytest.mark.parametrize("invalid", ["false", "true", 0, 1, None])
def test_shared_switch_requires_real_boolean(invalid: object) -> None:
    with pytest.raises(ValidationError):
        BotConfig.model_validate({"use_default_for_unconfigured_targets": invalid})


def test_shared_switch_defaults_off() -> None:
    assert BotConfig().use_default_for_unconfigured_targets is False


@pytest.mark.asyncio
async def test_bilibili_unconfigured_target_is_not_sent_or_notified() -> None:
    routes = PrivateConversationRoutes(onebot_enabled=False)
    delivery, messenger, subscriptions = _delivery(private_routes=routes)
    notices = AsyncMock()
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        admin_notices=cast("Any", notices),
    )
    item = {
        "id_str": "test-dynamic",
        "modules": {
            "module_author": {"mid": 12345, "name": "test"},
            "module_dynamic": {"desc": {"text": "body"}},
        },
    }
    await sender.send(item, 1, 12345, BiliPushTargets([], [], [PRIVATE], []))
    assert not messenger.calls
    notices.send_private_to_superusers.assert_not_awaited()
