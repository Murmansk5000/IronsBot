from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.messaging import MessageCommandAction
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import MentionPart, OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.storage.team_resources import TeamResourceSubscriptionStore
from ironsbot.services.operations.request_feedback import acknowledged_request_scope
from ironsbot.services.portable_messaging_commands import build_portable_text_operation
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import (
    PortableReply,
    deliver_portable_reply,
    slow_operation_reply,
)
from ironsbot.services.portable_seer_commands import build_peak_query_operation
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.team.resource import TeamResourceService
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceSubscriptionTarget,
    TeamResourceSubscriptionUpdate,
)
from ironsbot.services.team.subscription_confirmation import subscription_confirmation

if TYPE_CHECKING:
    from pathlib import Path


def _context(platform: Platform, *, account: str = "test-bot") -> MessageInputContext:
    actor = ActorRef(platform, "710001", account_id=account)
    group = ConversationRef(platform, "group", "720001", account_id=account)
    return MessageInputContext(
        IncomingMessageRef(
            platform, actor, group, "message", "战队730001", group_role="admin"
        ),
        mentions_bot=True,
    )


def _text(message: OutboundMessage) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("explicit", [True, False])
async def test_text_target_priority_and_no_extra_sender(
    platform: Platform,
    explicit: bool,  # noqa: FBT001
) -> None:
    context = _context(platform)
    selected = replace(context.message.actor, id="710002")
    configured = ActorRef(Platform.ONEBOT, "710003")
    resolved = replace(context.message.actor, id="710004")
    principals = Mock(official_group_member_for_qq=Mock(return_value=resolved))
    context = replace(
        context,
        message=replace(
            context.message, direct_mentions=(selected, selected) if explicit else ()
        ),
    )
    operation = build_portable_text_operation(
        MessageCommandAction(id="example", commands=["示例"], messages=["示例文本"]),
        (configured,),
        principals,
    )
    reply = await operation("示例", context)
    assert isinstance(reply, PortableReply)
    targets = [p.actor for p in reply.message.parts if isinstance(p, MentionPart)]
    expected = (
        selected
        if explicit
        else resolved
        if platform is Platform.QQ_OFFICIAL
        else configured
    )
    assert targets == [expected]
    if explicit:
        principals.official_group_member_for_qq.assert_not_called()


@pytest.mark.asyncio
async def test_missing_official_mention_does_not_send_configured_body() -> None:
    operation = build_portable_text_operation(
        MessageCommandAction(id="example", commands=["示例"], messages=["不应发送"]),
        (ActorRef(Platform.ONEBOT, "710002"),),
        Mock(official_group_member_for_qq=Mock(return_value=None)),
    )
    reply = await operation("示例", _context(Platform.QQ_OFFICIAL))
    assert isinstance(reply, PortableReply)
    assert "无法确认" in _text(reply.message)
    assert "不应发送" not in _text(reply.message)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("answer", ["y", "n", "0"])
async def test_team_confirmation_has_independent_owner_and_single_commit(
    tmp_path: Path,
    platform: Platform,
    answer: str,
) -> None:
    context = _context(platform)
    store = TeamResourceSubscriptionStore(tmp_path / "team.sqlite")
    features = FeatureService(
        {context.message.conversation: frozenset({"team_resource_subscription"})},
        {},
        frozenset(),
    )
    service = TeamResourceService(
        TeamResourceConfig(enabled=True),
        store,
        cast("Any", Mock()),
        features,
        cast("Any", Mock()),
    )
    suggestion = service.offer_subscription(
        conversation=context.message.conversation,
        actor=context.message.actor,
        team_id=730001,
        team_name="示例战队",
        can_manage=True,
    )
    assert suggestion is not None
    sessions = PortableQuerySessions()
    menu = subscription_confirmation(
        service, OutboundMessage.from_text(suggestion), context, sessions
    )
    assert menu.prompt is not None
    assert menu.prompt.choices[-1].label == "取消"
    stranger = replace(
        context,
        message=replace(
            context.message, actor=replace(context.message.actor, id="710009")
        ),
    )
    assert await sessions.interactions.select("y", stranger) is None
    assert (
        await sessions.interactions.select("y", _context(platform, account="other-bot"))
        is None
    )
    result = await sessions.interactions.select(answer, context)
    assert result is not None
    assert ("已订阅本群战队" in _text(result.message)) is (answer == "y")
    assert await sessions.interactions.select(answer, context) is None
    subscriptions = service.subscriptions_message(
        TeamResourceSubscriptionTarget(context.message.conversation)
    )
    assert ("730001" in subscriptions) is (answer == "y")


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_team_confirmation_rechecks_permission_and_timeout(
    tmp_path: Path,
    expired: bool,  # noqa: FBT001
) -> None:
    context = _context(Platform.ONEBOT)
    store = TeamResourceSubscriptionStore(tmp_path / "team.sqlite")
    features = FeatureService(
        {context.message.conversation: frozenset({"team_resource_subscription"})},
        {},
        frozenset(),
    )
    service = TeamResourceService(
        TeamResourceConfig(enabled=True),
        store,
        cast("Any", Mock()),
        features,
        cast("Any", Mock()),
    )
    text = service.offer_subscription(
        conversation=context.message.conversation,
        actor=context.message.actor,
        team_id=730001,
        team_name="示例战队",
        can_manage=True,
    )
    assert text is not None
    clock = [0.0]
    sessions = PortableQuerySessions(ttl_seconds=10, now=lambda: clock[0])
    subscription_confirmation(
        service, OutboundMessage.from_text(text), context, sessions
    )
    if expired:
        clock[0] = 11
    else:
        context = replace(
            context, message=replace(context.message, group_role="member")
        )
    result = await sessions.select("y", context)
    assert result is None or "已订阅本群战队" not in _text(result)
    pending = service.pending_prompt(context.message.conversation)
    assert pending is not None and pending.handled_at is None


@pytest.mark.asyncio
async def test_team_confirmation_preserves_a_subscription_added_while_waiting(
    tmp_path: Path,
) -> None:
    context = _context(Platform.ONEBOT)
    store = TeamResourceSubscriptionStore(tmp_path / "team.sqlite")
    features = FeatureService(
        {context.message.conversation: frozenset({"team_resource_subscription"})},
        {},
        frozenset(),
    )
    service = TeamResourceService(
        TeamResourceConfig(enabled=True),
        store,
        cast("Any", Mock()),
        features,
        cast("Any", Mock()),
    )
    suggestion = service.offer_subscription(
        conversation=context.message.conversation,
        actor=context.message.actor,
        team_id=730001,
        team_name="示例战队",
        can_manage=True,
    )
    assert suggestion is not None
    sessions = PortableQuerySessions()
    subscription_confirmation(
        service, OutboundMessage.from_text(suggestion), context, sessions
    )
    manual_threshold = 9123
    store.upsert(
        TeamResourceSubscriptionUpdate(
            context.message.conversation,
            730001,
            "示例战队",
            manual_threshold,
            (replace(context.message.actor, id="710003"),),
            context.message.actor,
        )
    )
    result = await sessions.select("y", context)
    assert result is not None
    assert "保留现有订阅设置" in _text(result)
    current = store.list_conversation(context.message.conversation)
    assert len(current) == 1
    assert current[0].threshold == manual_threshold
    assert current[0].mention_actors[0].id == "710003"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "rejected", "exception"])
async def test_slow_notice_failure_keeps_query_and_final_result(failure: str) -> None:
    ready = asyncio.Event()

    async def query() -> str:
        await ready.wait()
        return "最终结果"

    reply = await slow_operation_reply(query(), delay_seconds=0)
    sent = []

    async def send(message: OutboundMessage) -> SendResult:
        sent.append(_text(message))
        if len(sent) == 1:
            ready.set()
            if failure == "exception":
                raise OSError
            if failure == "rejected":
                return SendResult(delivered=False, error_code="test")
        return SendResult(delivered=True, message_id=str(len(sent)))

    assert await deliver_portable_reply(reply, send)
    assert sent == ["正在查询，完成后发送结果。", "最终结果"]


@pytest.mark.asyncio
async def test_fast_query_and_previously_acknowledged_query_have_no_notice() -> None:
    reply = await slow_operation_reply(AsyncMock(return_value="快速结果")())
    assert _text(reply.message) == "快速结果"
    assert reply.follow_up is None
    with acknowledged_request_scope():
        reply = await slow_operation_reply(
            AsyncMock(return_value="已有提示")(), delay_seconds=0
        )
    assert _text(reply.message) == "已有提示"
    assert reply.follow_up is None


@pytest.mark.asyncio
async def test_slow_peak_data_failure_uses_the_shared_error_message() -> None:
    ready = asyncio.Event()

    async def pool(**_kwargs: object) -> Any:
        await ready.wait()
        raise DataUnavailableError

    service = Mock(pool=pool)
    operation = build_peak_query_operation(service)
    context = _context(Platform.ONEBOT)
    reply = await operation("竞技池", context)
    assert isinstance(reply, PortableReply)
    assert reply.initial_is_advisory
    ready.set()
    assert reply.follow_up is not None
    assert _text(await reply.follow_up()) == DATABASE_UNAVAILABLE_MESSAGE
    if reply.on_finished is not None:
        reply.on_finished()
