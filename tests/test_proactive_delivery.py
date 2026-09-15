from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    MentionPart,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.promotions import PromotionCatalog, PromotionConfig
from ironsbot.services.activity.delivery import ActivityReminderDelivery
from ironsbot.services.activity.outbound_sender import ActivityReminderOutboundSender
from ironsbot.services.messaging.admin_notice_delivery import OutboundAdminNoticeSender
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryPolicy,
    ProactiveDeliveryRequest,
    ProactiveMessageDelivery,
)
from ironsbot.services.messaging.scheduled_delivery import ScheduledMessageDelivery
from ironsbot.services.messaging.scheduled_outbound import (
    ScheduledMessageOutboundSender,
)
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
)
from ironsbot.services.seer.lucky_skin_window_delivery import (
    LuckySkinWindowOutboundSender,
)
from ironsbot.services.team.resource_delivery import TeamResourceOutboundSender
from ironsbot.services.team.resource_subscriptions import TeamResourceSubscriptionTarget

if TYPE_CHECKING:
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository

GROUP = ConversationRef(Platform.ONEBOT, "group", "3003")
PRIVATE = ConversationRef(Platform.ONEBOT, "private", "1001")
UNSUPPORTED = ConversationRef(Platform.QQ_OFFICIAL, "group", "guild-1")
ACTOR = ActorRef(Platform.ONEBOT, "1001")
MENTION = ActorRef(Platform.ONEBOT, "2002")
RETRY_CALL_COUNT = 2
MAX_PARALLEL_TARGETS = 2


@dataclass
class FakeFeatures:
    enabled_groups: set[tuple[ConversationRef, str]] = field(default_factory=set)
    enabled_actors: set[tuple[ActorRef, str]] = field(default_factory=set)

    def actor_has_feature(self, actor: ActorRef, feature: str) -> bool:
        return (actor, feature) in self.enabled_actors

    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        return (conversation, feature) in self.enabled_groups


@dataclass
class FakeSubscriptions:
    allowed: set[ConversationRef] | None = None
    unsubscribed: set[tuple[ConversationRef, str]] = field(default_factory=set)
    daily_hints_allowed: bool = True
    hint_calls: list[tuple[ConversationRef, str]] = field(default_factory=list)

    def filter_subscribed_conversations(
        self,
        conversations: list[ConversationRef],
        _subscription_key: str,
    ) -> list[ConversationRef]:
        if self.allowed is None:
            return conversations
        return [
            conversation
            for conversation in conversations
            if conversation in self.allowed
        ]

    def mark_daily_hint_sent(
        self,
        conversation: ConversationRef,
        hint_key: str,
        *,
        today: str | None = None,
    ) -> bool:
        del today
        self.hint_calls.append((conversation, hint_key))
        return self.daily_hints_allowed

    def is_unsubscribed(
        self,
        conversation: ConversationRef,
        subscription_key: str,
    ) -> bool:
        return (conversation, subscription_key) in self.unsubscribed


@dataclass
class FakeMessenger:
    failed: set[ConversationRef] = field(default_factory=set)
    scripted_results: list[SendResult] = field(default_factory=list)
    calls: list[tuple[ConversationRef, OutboundMessage]] = field(default_factory=list)

    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        supported = conversation.platform is Platform.ONEBOT
        return DeliveryCapabilities(
            can_reply_to_event=supported,
            can_send_proactively=supported,
            can_mention_members=supported,
            supports_group_context=supported,
            supports_private_context=supported,
            supports_images=supported,
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        self.calls.append((conversation, message))
        if self.scripted_results:
            return self.scripted_results.pop(0)
        if conversation in self.failed:
            return SendResult(delivered=False, error_code="delivery_failed")
        return SendResult(delivered=True, message_id=f"message-{len(self.calls)}")

    async def reply(self, *_args: object, **_kwargs: object) -> SendResult:
        return SendResult(delivered=False, error_code="unsupported")


@dataclass
class _ConcurrentMessenger(FakeMessenger):
    active: int = 0
    max_active: int = 0

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        self.calls.append((conversation, message))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return SendResult(delivered=True, message_id=f"message-{len(self.calls)}")
        finally:
            self.active -= 1


def _delivery(
    *,
    features: FakeFeatures | None = None,
    subscriptions: FakeSubscriptions | None = None,
    messenger: FakeMessenger | None = None,
    policy: ProactiveDeliveryPolicy | None = None,
) -> tuple[ProactiveMessageDelivery, FakeMessenger, FakeSubscriptions]:
    resolved_features = features or FakeFeatures()
    resolved_subscriptions = subscriptions or FakeSubscriptions()
    resolved_messenger = messenger or FakeMessenger()
    return (
        ProactiveMessageDelivery(
            resolved_messenger,  # type: ignore[arg-type]
            resolved_features,  # type: ignore[arg-type]
            PromotionCatalog(
                {
                    "manual": PromotionConfig(
                        feature="fire_manual",
                        text="手册：{url}",
                        url="https://example.test/manual",
                        append_to_push=True,
                    )
                }
            ),
            resolved_subscriptions,  # type: ignore[arg-type]
            PushUnsubscribeConfig(hint="私聊提示", group_hint="群聊提示"),
            policy or ProactiveDeliveryPolicy(retry_delay_seconds=0),
        ),
        resolved_messenger,
        resolved_subscriptions,
    )


def _text(message: OutboundMessage) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


@pytest.mark.asyncio
async def test_proactive_delivery_filters_subscriptions_and_applies_policy_per_target(
) -> None:
    features = FakeFeatures(enabled_groups={(GROUP, "fire_manual")})
    delivery, messenger, subscriptions = _delivery(
        features=features,
        subscriptions=FakeSubscriptions(allowed={GROUP, PRIVATE}),
    )

    summary = await delivery.send(
        OutboundMessage((TextPart("定时消息"),)),
        (GROUP, PRIVATE, GROUP, UNSUPPORTED),
        action_name="scheduled message",
        interval_seconds=0,
        subscription_key="daily",
        include_promotions=True,
    )

    assert summary.succeeded == (GROUP, PRIVATE)
    assert summary.failed == ()
    assert [conversation for conversation, _message in messenger.calls] == [
        GROUP,
        PRIVATE,
    ]
    assert _text(messenger.calls[0][1]) == (
        "定时消息\n\n手册：https://example.test/manual\n\n群聊提示"
    )
    assert _text(messenger.calls[1][1]) == "定时消息\n\n私聊提示"
    assert subscriptions.hint_calls == [
        (GROUP, "push_subscription_hint"),
        (PRIVATE, "push_subscription_hint"),
    ]


@pytest.mark.asyncio
async def test_proactive_delivery_returns_transport_and_capability_failures() -> None:
    delivery, messenger, _subscriptions = _delivery(
        messenger=FakeMessenger(failed={GROUP}),
    )

    summary = await delivery.send(
        OutboundMessage((TextPart("通知"),)),
        (GROUP, UNSUPPORTED),
        action_name="notice",
        interval_seconds=0,
    )

    assert summary.succeeded == ()
    assert summary.failed == (GROUP, UNSUPPORTED)
    assert [conversation for conversation, _message in messenger.calls] == [GROUP]


@pytest.mark.asyncio
async def test_proactive_delivery_retries_only_explicitly_retryable_failures() -> None:
    messenger = FakeMessenger(
        scripted_results=[
            SendResult(
                delivered=False,
                error_code="temporary",
                failure_kind=DeliveryFailureKind.RETRYABLE,
            ),
            SendResult(delivered=True, message_id="recovered"),
        ]
    )
    delivery, _messenger, _subscriptions = _delivery(messenger=messenger)

    summary = await delivery.send(
        OutboundMessage((TextPart("通知"),)),
        (GROUP,),
        action_name="retry",
        interval_seconds=0,
    )

    assert summary.succeeded == (GROUP,)
    assert summary.failed == ()
    assert len(messenger.calls) == RETRY_CALL_COUNT


@pytest.mark.asyncio
async def test_proactive_delivery_does_not_retry_uncertain_delivery() -> None:
    messenger = FakeMessenger(
        scripted_results=[
            SendResult(
                delivered=False,
                error_code="timeout",
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            )
        ]
    )
    delivery, _messenger, _subscriptions = _delivery(messenger=messenger)

    summary = await delivery.send(
        OutboundMessage((TextPart("通知"),)),
        (GROUP,),
        action_name="uncertain",
        interval_seconds=0,
    )

    assert summary.failed == (GROUP,)
    assert summary.uncertain == (GROUP,)
    assert len(messenger.calls) == 1


@pytest.mark.asyncio
async def test_proactive_delivery_stops_after_transport_becomes_unavailable() -> None:
    second = ConversationRef(Platform.ONEBOT, "group", "3004")
    messenger = FakeMessenger(
        scripted_results=[
            SendResult(
                delivered=False,
                error_code="offline",
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            )
        ]
    )
    delivery, _messenger, _subscriptions = _delivery(
        messenger=messenger,
        policy=ProactiveDeliveryPolicy(
            max_parallel_targets=1,
            retry_delay_seconds=0,
        ),
    )

    summary = await delivery.send(
        OutboundMessage((TextPart("通知"),)),
        (GROUP, second),
        action_name="offline",
        interval_seconds=0,
    )

    assert summary.failed == (GROUP, second)
    assert [conversation for conversation, _message in messenger.calls] == [GROUP]


@pytest.mark.asyncio
async def test_proactive_delivery_bounds_parallel_transport_calls() -> None:
    conversations = tuple(
        ConversationRef(Platform.ONEBOT, "group", str(group_id))
        for group_id in range(3003, 3009)
    )
    messenger = _ConcurrentMessenger()
    delivery, _messenger, _subscriptions = _delivery(
        messenger=messenger,
        policy=ProactiveDeliveryPolicy(
            max_parallel_targets=MAX_PARALLEL_TARGETS,
            retry_delay_seconds=0,
        ),
    )

    summary = await delivery.send(
        OutboundMessage((TextPart("通知"),)),
        conversations,
        action_name="bounded",
        interval_seconds=0,
    )

    assert summary.succeeded == conversations
    assert messenger.max_active == MAX_PARALLEL_TARGETS


@pytest.mark.asyncio
async def test_specialized_outbound_senders_keep_typed_targets_and_mentions() -> None:
    delivery, messenger, _subscriptions = _delivery()

    activity_sent = await ActivityReminderOutboundSender(delivery).send(
        ActivityReminderDelivery(
            status="send",
            message=OutboundMessage((TextPart("活动即将结束"),)),
            group_conversations=(GROUP,),
            private_actors=(ACTOR,),
            action_name="activity reminder",
        )
    )
    team_sent = await TeamResourceOutboundSender(delivery).send_low_resource_notice(
        TeamResourceSubscriptionTarget(GROUP, (MENTION,)),
        "战队资源不足",
    )
    await ScheduledMessageOutboundSender(delivery).send(
        ScheduledMessageDelivery(
            messages=("定时推送一", "定时推送二"),
            private_conversations=(PRIVATE,),
            group_conversations=(GROUP,),
            group_mentions=(MENTION,),
            action_name="schedule",
            subscription_key="schedule",
        )
    )

    assert activity_sent
    assert team_sent
    assert [conversation for conversation, _message in messenger.calls] == [
        GROUP,
        PRIVATE,
        GROUP,
        PRIVATE,
        GROUP,
        PRIVATE,
        GROUP,
    ]
    assert isinstance(messenger.calls[2][1].parts[0], MentionPart)
    assert messenger.calls[2][1].parts[0].actor == MENTION
    assert isinstance(messenger.calls[4][1].parts[0], MentionPart)
    assert messenger.calls[4][1].parts[0].actor == MENTION
    assert isinstance(messenger.calls[6][1].parts[0], MentionPart)
    assert messenger.calls[6][1].parts[0].actor == MENTION


@pytest.mark.asyncio
async def test_activity_sender_skips_empty_reminders() -> None:
    delivery, messenger, _subscriptions = _delivery()

    sent = await ActivityReminderOutboundSender(delivery).send(
        ActivityReminderDelivery(status="skip_empty")
    )

    assert not sent
    assert messenger.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ("unsubscribed", "duplicate"))
async def test_lucky_skin_sender_skips_unsubscribed_or_duplicate_notice(
    scenario: str,
) -> None:
    subscriptions = FakeSubscriptions(
        unsubscribed=(
            {(PRIVATE, LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY)}
            if scenario == "unsubscribed"
            else set()
        ),
        daily_hints_allowed=scenario != "duplicate",
    )
    delivery, messenger, _subscriptions = _delivery(subscriptions=subscriptions)

    sender = LuckySkinWindowOutboundSender(
        delivery,
        cast("PushSubscriptionRepository", subscriptions),
    )
    sent = await sender.send_daily_notice(
        ActorRef(Platform.ONEBOT, PRIVATE.id),
        "今日幸运橱窗。",
        day="2026-08-05",
    )

    assert not sent
    assert messenger.calls == []


@pytest.mark.asyncio
async def test_lucky_skin_sender_uses_typed_private_delivery() -> None:
    delivery, messenger, subscriptions = _delivery()

    sender = LuckySkinWindowOutboundSender(
        delivery,
        cast("PushSubscriptionRepository", subscriptions),
    )
    sent = await sender.send_daily_notice(
        ActorRef(Platform.ONEBOT, PRIVATE.id),
        "今日幸运橱窗。",
        day="2026-08-05",
    )

    assert sent
    assert subscriptions.hint_calls == [
        (PRIVATE, "lucky_skin_window_delivery"),
        (PRIVATE, "push_subscription_hint"),
    ]
    assert [conversation for conversation, _message in messenger.calls] == [PRIVATE]
    assert _text(messenger.calls[0][1]) == "今日幸运橱窗。\n\n私聊提示"


@pytest.mark.asyncio
async def test_admin_notice_sender_maps_delivery_summary_back_to_original_recipients(
) -> None:
    delivery, _messenger, _subscriptions = _delivery()
    sender = OutboundAdminNoticeSender(delivery)

    summary = await sender.send_admin_notice(
        OutboundMessage((TextPart("同步失败"),)),
        private_actors=(ACTOR,),
        group_conversations=(GROUP,),
        subscription_key="admin_notice",
        action_name="sync notice",
        interval_seconds=0,
    )

    assert summary.succeeded == (ACTOR, GROUP)
    assert summary.failed == ()


@pytest.mark.asyncio
async def test_send_many_uses_the_first_message_for_duplicate_conversations() -> None:
    delivery, messenger, _subscriptions = _delivery()

    summary = await delivery.send_many(
        (
            ProactiveDeliveryRequest(GROUP, OutboundMessage((TextPart("first"),))),
            ProactiveDeliveryRequest(GROUP, OutboundMessage((TextPart("second"),))),
        ),
        action_name="dedupe",
        interval_seconds=0,
    )

    assert summary.succeeded == (GROUP,)
    assert _text(messenger.calls[0][1]) == "first"
