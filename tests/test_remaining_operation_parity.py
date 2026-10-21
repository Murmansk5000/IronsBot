from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from ironsbot.config.models.ai import AiConfig
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.onebot.matcher_support import (
    RUNTIME_CONTEXT_TOKEN_STATE_KEY,
    register_runtime_context,
)
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_operation_handler,
)
from ironsbot.integrations.onebot.request_state import IN_FLIGHT_REQUEST_TOKEN_STATE_KEY
from ironsbot.services.ai.chat_operation import execute_chat
from ironsbot.services.portable_bilibili_commands import (
    build_portable_bilibili_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_rank_commands import (
    build_portable_rank_admin_operations,
)
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_resource_operations,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.team.resource_subscriptions import (
    parse_team_resource_manage_command,
)
from tests.helpers.onebot_events import group_message_event


def _context(platform: Platform, role: str = "member") -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "810001"),
            ConversationRef(platform, "group", "820001"),
            "request",
            "订阅战队830001",
            group_role=role,
        ),
        mentions_bot=True,
    )


def test_removed_ai_waiting_option_is_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AiConfig.model_validate({"waiting_notice": False})


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_bilibili_management_rechecks_authorization(platform: Platform) -> None:
    features = Mock(
        is_message_blocked=Mock(return_value=False),
        is_actor_superuser=Mock(return_value=False),
        is_feature_allowed=Mock(return_value=True),
    )
    service = Mock()
    service.targets.update_push_mode = AsyncMock(return_value="updated")
    refresh = AsyncMock(return_value="refreshed")
    operations = build_portable_bilibili_operations(
        service,
        PortableQuerySessions(),
        features=features,
        notify_auth_invalid=AsyncMock(),
        refresh_now=refresh,
    )
    member = _context(platform)
    assert await operations["bilibili.refresh"]("/刷新动态", member) is None
    assert (
        await operations["bilibili.push_mode"]("B站推送模式 sample 内容", member)
        is None
    )
    refresh.assert_not_awaited()
    service.targets.update_push_mode.assert_not_awaited()
    await operations["bilibili.push_mode"](
        "B站推送模式 sample 内容", _context(platform, "admin")
    )
    service.targets.update_push_mode.assert_awaited_once()
    features.is_actor_superuser.return_value = True
    reply = await operations["bilibili.refresh"]("/刷新动态", member)
    assert isinstance(reply, PortableReply)
    assert reply.message == OutboundMessage.from_text("refreshed")
    features.is_message_blocked.return_value = True
    assert await operations["bilibili.refresh"]("/刷新动态", member) is None
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_bilibili_refresh_failure_is_not_a_successful_query() -> None:
    operations = build_portable_bilibili_operations(
        Mock(),
        PortableQuerySessions(),
        notify_auth_invalid=AsyncMock(),
        refresh_now=AsyncMock(side_effect=ConnectionError),
    )
    result = await operations["bilibili.refresh"](
        "/刷新动态", _context(Platform.ONEBOT)
    )
    assert isinstance(result, PortableReply)
    assert not result.message.request_succeeded


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_shared_ai_only_returns_final_response(platform: Platform) -> None:
    service = Mock(chat_reply=AsyncMock(return_value="final"))
    context = _context(platform)
    assert (
        await execute_chat(service, context, " question ", source_context="source")
        == "final"
    )
    service.chat_reply.assert_awaited_once_with(
        actor=context.message.actor,
        conversation=context.message.conversation,
        prompt="question",
        source_context="source",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_subscription_execution_rechecks_role(platform: Platform) -> None:
    service = Mock(
        allows_target=Mock(return_value=True),
        is_superuser=Mock(return_value=False),
        parse_manage=parse_team_resource_manage_command,
        add_target_subscription=AsyncMock(return_value="subscribed"),
    )
    operations = build_portable_team_resource_operations(
        service, Mock(), Mock(), PortableQuerySessions()
    )
    context = _context(platform)
    denied = await operations["team_resource.subscribe"](context.text, context)
    assert isinstance(denied, OutboundMessage)
    assert not denied.request_succeeded
    service.add_target_subscription.assert_not_awaited()
    admin = _context(platform, "admin")
    await operations["team_resource.subscribe"](admin.text, admin)
    service.add_target_subscription.assert_awaited_once()


@pytest.mark.asyncio
async def test_stateless_query_failure_releases_duplicate_admission() -> None:
    requests = Mock()
    state = {
        RUNTIME_CONTEXT_TOKEN_STATE_KEY: register_runtime_context(requests),
        IN_FLIGHT_REQUEST_TOKEN_STATE_KEY: "admission",
    }
    matcher = Mock(state=state, send=AsyncMock(return_value={"message_id": 840001}))
    operation = AsyncMock(side_effect=DataUnavailableError())
    await make_portable_operation_handler(operation)(
        matcher, state, group_message_event("数据版本")
    )
    matcher.send.assert_awaited_once()
    requests.release.assert_called_once_with("admission")
    assert IN_FLIGHT_REQUEST_TOKEN_STATE_KEY not in state


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_slow_rank_refresh_survives_notice_failure(platform: Platform) -> None:
    release = asyncio.Event()

    async def refresh(*, actor: object, progress: Any) -> str:
        assert actor == _context(platform).message.actor
        await progress("stage one")
        await release.wait()
        await progress("stage two")
        return "complete"

    operation = build_portable_rank_admin_operations(Mock(cache_refresh=refresh))[
        "rank.sample_refresh"
    ]
    reply = await operation("刷新样本", _context(platform))
    assert isinstance(reply, PortableReply)
    assert reply.initial_is_advisory
    sent = []

    async def send(message: OutboundMessage) -> SendResult:
        sent.append(message)
        if len(sent) == 1:
            release.set()
            raise ConnectionError
        return SendResult(delivered=True, message_id="final")

    assert await deliver_portable_reply(reply, send)
    notice, final = sent
    assert notice == reply.message
    assert final == OutboundMessage.from_text("complete")
