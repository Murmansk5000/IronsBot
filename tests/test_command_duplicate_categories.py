from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    DuplicateWindowConfig,
)
from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from tests.helpers.onebot_events import group_message_event
from tests.helpers.onebot_inputs import message_input_context

ACTOR = ActorRef(Platform.ONEBOT, "101")
GROUP = ConversationRef(Platform.ONEBOT, "group", "456")


@dataclass
class Features:
    def is_actor_superuser(self, actor: ActorRef) -> bool:
        del actor
        return False


def request(
    category: RequestCategory,
    *,
    source: SemanticRequestSource = SemanticRequestSource.DIRECT,
) -> SemanticRequest:
    return SemanticRequest(
        ActionDefinition("example.read", "读取", category=category),
        SemanticTarget("123456", "玩家"),
        source,
    )


def test_defaults_and_legacy_scalar() -> None:
    assert CommandCooldownConfig().duplicate_window_seconds == DuplicateWindowConfig()
    assert CommandCooldownConfig.model_validate(
        {"duplicate_window_seconds": 45}
    ).duplicate_window_seconds == DuplicateWindowConfig(taomee=45, other_network=45)


@pytest.mark.parametrize("value", [-1, True, "120", float("inf"), float("nan")])
def test_invalid_category_duration(value: object) -> None:
    with pytest.raises(ValidationError):
        CommandCooldownConfig.model_validate(
            {"duplicate_window_seconds": {"local": value}}
        )


def test_unknown_category_and_unregistered_action_rejected() -> None:
    with pytest.raises(ValidationError):
        CommandCooldownConfig.model_validate({"duplicate_window_seconds": {"typo": 0}})
    with pytest.raises(ValueError, match="explicit category"):
        ActionDefinition("unregistered.action", "未登记")


@pytest.mark.parametrize("category", list(RequestCategory))
def test_independent_windows_and_menu_direct_identity(
    category: RequestCategory,
) -> None:
    windows = DuplicateWindowConfig(taomee=12, local=0, other_network=24)
    service = InFlightRequestService(
        Features(), CommandCooldownConfig(duplicate_window_seconds=windows)
    )
    first = service.admit(
        actor=ACTOR, conversation=GROUP, request=request(category), now=0
    )
    # Active tasks stay protected even for zero or beyond the completion window.
    assert not service.admit(
        actor=ACTOR,
        conversation=GROUP,
        request=request(category, source=SemanticRequestSource.MENU),
        now=1000,
    ).allowed
    service.finish(first.token, now=1001)
    delay = getattr(windows, category.value)
    if delay:
        assert not service.admit(
            actor=ACTOR,
            conversation=GROUP,
            request=request(category),
            now=1001 + delay - 0.1,
        ).allowed
    assert service.admit(
        actor=ACTOR, conversation=GROUP, request=request(category), now=1001 + delay
    ).allowed


def test_release_and_bot_isolation() -> None:
    service = InFlightRequestService(Features(), CommandCooldownConfig())
    query = request(RequestCategory.TAOMEE)
    a = service.admit(actor=ACTOR, conversation=GROUP, request=query, bot_id="a")
    b = service.admit(actor=ACTOR, conversation=GROUP, request=query, bot_id="b")
    assert a.allowed and b.allowed
    service.release(a.token)
    assert service.admit(
        actor=ACTOR, conversation=GROUP, request=query, bot_id="a"
    ).allowed
    assert not service.admit(
        actor=ACTOR, conversation=GROUP, request=query, bot_id="b"
    ).allowed


@pytest.mark.parametrize(
    ("action_id", "category"),
    [
        ("help", RequestCategory.LOCAL),
        ("messaging.push_subscription", RequestCategory.LOCAL),
        ("seer.pet.query", RequestCategory.LOCAL),
        ("seer.player.bind", RequestCategory.LOCAL),
        ("private_player_lineup", RequestCategory.TAOMEE),
        ("seer.player.collection", RequestCategory.TAOMEE),
        ("seer.lucky_skin_window.query", RequestCategory.TAOMEE),
        ("bilibili.dynamic", RequestCategory.OTHER_NETWORK),
        ("ai_chat", RequestCategory.OTHER_NETWORK),
    ],
)
def test_business_action_inventory(action_id: str, category: RequestCategory) -> None:
    assert ActionDefinition(action_id, action_id).category is category


@pytest.mark.asyncio
@pytest.mark.parametrize("deferred", [False, True])
async def test_failed_business_reply_does_not_create_completed_cooldown(
    *, deferred: bool
) -> None:
    sessions = PortableQuerySessions()
    service = InFlightRequestService(Features(), CommandCooldownConfig())
    sessions.interactions.request_service = service
    context = message_input_context(group_message_event("收集123456", user_id=101))
    query = request(RequestCategory.TAOMEE)

    async def failed_result() -> OutboundMessage:
        return OutboundMessage.from_text("查询超时", request_succeeded=False)

    async def operation() -> PortableReply:
        if deferred:
            return PortableReply(
                OutboundMessage.from_text("查询中"), follow_up=failed_result
            )
        return PortableReply(await failed_result())

    reply = await sessions.interactions.execute_request(query, context, operation)
    assert reply is not None

    async def send(_message: OutboundMessage) -> SendResult:
        return SendResult(delivered=True, message_id="result")

    assert await deliver_portable_reply(reply, send)
    assert reply.outcome.failed
    assert service.admit(
        actor=context.message.actor,
        conversation=context.message.conversation,
        bot_id=context.request_bot_id,
        request=query,
    ).allowed
