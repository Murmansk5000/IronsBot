from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.outbound import (
    DeliveryCapabilities,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _Messenger:
    calls: list[tuple[ConversationRef, OutboundMessage]] = field(default_factory=list)

    def capabilities_for(self, _conversation: ConversationRef) -> DeliveryCapabilities:
        return DeliveryCapabilities(
            can_reply_to_event=True,
            can_send_proactively=True,
            can_mention_members=True,
            supports_group_context=True,
            supports_private_context=True,
            supports_images=True,
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        self.calls.append((conversation, message))
        return SendResult(delivered=True, message_id=str(len(self.calls)))

    async def reply(self, *_args: object, **_kwargs: object) -> SendResult:
        return SendResult(delivered=False, error_code="unsupported")


def _delivery(
    config: PushUnsubscribeConfig,
    store: PushUnsubscribeStore,
) -> tuple[ProactiveMessageDelivery, _Messenger]:
    messenger = _Messenger()
    runtime = build_test_runtime(push_unsubscribe=config)
    return (
        ProactiveMessageDelivery(
            messenger,  # type: ignore[arg-type]
            runtime.features,
            PromotionCatalog({}),
            store,
            config,
        ),
        messenger,
    )


def _group(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _private(user_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "private", str(user_id))


def _text(message: OutboundMessage) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


def _sent_texts(
    messenger: _Messenger,
) -> list[tuple[ConversationRef, str]]:
    return [
        (conversation, _text(message))
        for conversation, message in messenger.calls
    ]


def test_proactive_delivery_filters_unsubscribed_push_targets(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "qq_state.sqlite"
    config = PushUnsubscribeConfig(
        hint="回复 TD 管理推送。",
        group_hint="群管理发送 TD 管理推送。",
    )
    store = PushUnsubscribeStore(state_path)
    store.unsubscribe(_private(1001), "bili_push", "bili_push")
    store.unsubscribe(_group(2001), "bili_push", "bili_push")
    delivery, messenger = _delivery(config, store)

    summary = asyncio.run(
        delivery.send(
            OutboundMessage((TextPart("推送正文"),)),
            (_private(1001), _private(1002), _group(2001), _group(2002)),
            action_name="Bilibili push",
            interval_seconds=0,
            subscription_key="bili_push",
        )
    )

    assert summary.succeeded == (_private(1002), _group(2002))
    assert _sent_texts(messenger) == [
        (_private(1002), "推送正文\n\n回复 TD 管理推送。"),
        (_group(2002), "推送正文\n\n群管理发送 TD 管理推送。"),
    ]


def test_proactive_delivery_does_not_share_mutated_messages_between_targets(
    tmp_path: Path,
) -> None:
    config = PushUnsubscribeConfig(
        hint="回复 TD 管理私聊推送。",
        group_hint="群主/管理员发送 TD 管理本群推送。",
    )
    delivery, messenger = _delivery(
        config,
        PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
    )

    asyncio.run(
        delivery.send(
            OutboundMessage((TextPart("机器人已开启。"),)),
            (_group(2001), _private(1001)),
            action_name="startup notice",
            interval_seconds=0,
            subscription_key="startup_notice",
        )
    )

    assert _sent_texts(messenger) == [
        (_group(2001), "机器人已开启。\n\n群主/管理员发送 TD 管理本群推送。"),
        (_private(1001), "机器人已开启。\n\n回复 TD 管理私聊推送。"),
    ]


def test_proactive_delivery_appends_subscription_hint_once_per_day(
    tmp_path: Path,
) -> None:
    config = PushUnsubscribeConfig(
        hint="回复 TD 管理私聊推送。",
        group_hint="群主/管理员发送 TD 管理本群推送。",
    )
    delivery, messenger = _delivery(
        config,
        PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
    )
    targets = (_private(1001), _group(2001))

    asyncio.run(
        delivery.send(
            OutboundMessage((TextPart("第一次"),)),
            targets,
            action_name="startup notice",
            interval_seconds=0,
            subscription_key="startup_notice",
        )
    )
    asyncio.run(
        delivery.send(
            OutboundMessage((TextPart("第二次"),)),
            targets,
            action_name="startup notice",
            interval_seconds=0,
            subscription_key="startup_notice",
        )
    )
    asyncio.run(
        delivery.send(
            OutboundMessage((TextPart("另一个群"),)),
            (_group(2002),),
            action_name="startup notice",
            interval_seconds=0,
            subscription_key="startup_notice",
        )
    )

    assert _sent_texts(messenger) == [
        (_private(1001), "第一次\n\n回复 TD 管理私聊推送。"),
        (_group(2001), "第一次\n\n群主/管理员发送 TD 管理本群推送。"),
        (_private(1001), "第二次"),
        (_group(2001), "第二次"),
        (_group(2002), "另一个群\n\n群主/管理员发送 TD 管理本群推送。"),
    ]
