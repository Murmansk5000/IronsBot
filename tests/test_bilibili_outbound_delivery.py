from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.core.outbound import OutboundMessage, RemoteImagePart, TextPart
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.bilibili.outbound_delivery import (
    BILI_PUSH_ADMIN_HINT,
    CATEGORY_SUBSCRIPTION_HINT,
    DYNAMIC_HISTORY_HINT,
    FULL_DYNAMIC_PUSH_ACTION,
    LINK_DYNAMIC_PUSH_ACTION,
    BilibiliDynamicOutboundSender,
    render_dynamic_image_message,
    render_dynamic_link_message,
    render_dynamic_text_message,
)
from ironsbot.services.bilibili.preferences import (
    bili_media_subscription_key,
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryRequest,
    ProactiveDeliverySummary,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


PUB_TS = 1781004683
AUTHOR_MID = 1310714247


def _group(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _private(user_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "private", str(user_id))


def _targets(
    *,
    full_groups: tuple[int, ...] = (),
    link_groups: tuple[int, ...] = (),
    full_users: tuple[int, ...] = (),
    link_users: tuple[int, ...] = (),
) -> BiliPushTargets:
    return BiliPushTargets(
        full_group_conversations=[_group(group_id) for group_id in full_groups],
        link_group_conversations=[_group(group_id) for group_id in link_groups],
        full_private_conversations=[_private(user_id) for user_id in full_users],
        link_private_conversations=[_private(user_id) for user_id in link_users],
    )


def _item(
    *,
    text: str = "这是一条普通动态，正文内容应该只在全文模式里出现",
    include_image: bool = True,
) -> dict[str, Any]:
    return {
        "id_str": "1211894957538803730",
        "modules": {
            "module_author": {
                "mid": 1310714247,
                "name": "赛尔号",
                "pub_ts": PUB_TS,
            },
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": text},
                        "pics": (
                            [{"url": "http://i0.hdslb.com/bfs/new_dyn/test.jpg]"}]
                            if include_image
                            else []
                        ),
                    }
                }
            },
        },
    }


@dataclass
class _RecordingDelivery:
    link_calls: list[dict[str, object]] = field(default_factory=list)
    content_calls: list[dict[str, object]] = field(default_factory=list)
    content_failures: int = 0

    async def send_many(
        self,
        requests: Iterable[ProactiveDeliveryRequest],
        **kwargs: object,
    ) -> ProactiveDeliverySummary:
        selected = tuple(requests)
        self.link_calls.append({"requests": selected, **kwargs})
        conversations = tuple(
            request.conversation
            for request in selected
            if isinstance(request, ProactiveDeliveryRequest)
        )
        return ProactiveDeliverySummary(conversations, ())

    async def send(
        self,
        message: OutboundMessage,
        conversations: Iterable[ConversationRef],
        **kwargs: object,
    ) -> ProactiveDeliverySummary:
        selected = tuple(conversations)
        self.content_calls.append(
            {"message": message, "conversations": selected, **kwargs}
        )
        if len(self.content_calls) <= self.content_failures:
            return ProactiveDeliverySummary((), selected)
        return ProactiveDeliverySummary(selected, ())


@dataclass
class _RecordingAdminNotices:
    messages: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    async def send_private_to_superusers(
        self,
        message: str,
        **kwargs: object,
    ) -> None:
        self.messages.append((message, kwargs))


def test_portable_renderers_keep_text_and_remote_images() -> None:
    link = render_dynamic_link_message(_item(), PUB_TS)
    text = render_dynamic_text_message(_item())
    images = render_dynamic_image_message(_item())

    assert link is not None
    assert text is not None
    assert images is not None
    assert "传送门：" in str(link.parts[0])
    assert "正文内容" in str(text.parts[0])
    assert isinstance(images.parts[0], RemoteImagePart)
    assert images.parts[0].url == "http://i0.hdslb.com/bfs/new_dyn/test.jpg"


@pytest.mark.asyncio
async def test_full_dynamic_sends_links_then_portable_content_with_hints(
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery()
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        can_query_history=lambda conversation: conversation == _group(1001),
    )

    await sender.send(
        _item(),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001,), link_groups=(1002,)),
    )

    assert [call["action_name"] for call in delivery.link_calls] == [
        LINK_DYNAMIC_PUSH_ACTION,
        f"{FULL_DYNAMIC_PUSH_ACTION} link",
    ]
    assert [
        type(call["message"].parts[0])
        for call in delivery.content_calls
        if isinstance(call["message"], OutboundMessage)
    ] == [TextPart, RemoteImagePart]
    full_link = delivery.link_calls[1]["requests"]
    assert isinstance(full_link, tuple)
    message = full_link[0].message
    text = _message_text(message)
    assert DYNAMIC_HISTORY_HINT in text
    assert BILI_PUSH_ADMIN_HINT in text
    assert "传送门：" in text
    content = delivery.content_calls[0]["message"]
    assert isinstance(content, OutboundMessage)
    assert "正文内容" in _message_text(content)
    image = delivery.content_calls[1]["message"]
    assert isinstance(image, OutboundMessage)
    assert isinstance(image.parts[0], RemoteImagePart)
    assert not delivery.content_calls[0].get("subscription_key")


@pytest.mark.asyncio
async def test_category_subscription_hint_is_sent_for_configured_accounts(
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery()
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        has_category_subscriptions=lambda uid: uid == AUTHOR_MID,
    )

    await sender.send(
        _item(),
        PUB_TS,
        AUTHOR_MID,
        _targets(link_groups=(1001,), link_users=(2001,)),
    )

    requests = delivery.link_calls[0]["requests"]
    assert isinstance(requests, tuple)
    assert all(
        CATEGORY_SUBSCRIPTION_HINT in _message_text(request.message)
        for request in requests
    )


@pytest.mark.asyncio
async def test_content_failure_after_shared_policy_notifies_admins(
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery(content_failures=1)
    admin_notices = _RecordingAdminNotices()
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        admin_notices=admin_notices,  # type: ignore[arg-type]
    )

    await sender.send(
        _item(include_image=False),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001,), full_users=(2001,)),
    )

    assert len(delivery.content_calls) == 1
    assert len(admin_notices.messages) == 1
    message, kwargs = admin_notices.messages[0]
    assert "群：1001" in message
    assert "私聊：2001" in message
    assert kwargs["action_name"] == "Bilibili dynamic content delivery failure"


@pytest.mark.asyncio
async def test_full_dynamic_uses_summary_only_for_long_content(
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery()
    summary_calls: list[tuple[str, int]] = []

    async def summarize(content: str, max_chars: int) -> str:
        summary_calls.append((content, max_chars))
        return "这是忠实摘要。"

    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        summarize=summarize,
        content_max_chars=10,
        summary_max_chars=8,
    )
    content = "这是一条超过十个字符的长动态正文，用于验证统一摘要投递。"

    await sender.send(
        _item(text=content),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001,), link_groups=(1002,)),
    )

    assert summary_calls == [(content, 8)]
    assert [call["action_name"] for call in delivery.link_calls] == [
        LINK_DYNAMIC_PUSH_ACTION,
        f"{FULL_DYNAMIC_PUSH_ACTION} link",
    ]
    assert delivery.content_calls[0]["action_name"] == FULL_DYNAMIC_PUSH_ACTION
    message = delivery.content_calls[0]["message"]
    assert isinstance(message, OutboundMessage)
    assert message.parts[0] == TextPart("这是忠实摘要。")
    image = delivery.content_calls[1]["message"]
    assert isinstance(image, OutboundMessage)
    assert isinstance(image.parts[0], RemoteImagePart)


@pytest.mark.asyncio
async def test_short_dynamic_does_not_call_ai_summary(tmp_path: Path) -> None:
    delivery = _RecordingDelivery()

    async def unexpected_summary(_content: str, _max_chars: int) -> str:
        raise AssertionError

    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        summarize=unexpected_summary,
        content_max_chars=100,
        summary_max_chars=6,
    )

    await sender.send(
        _item(text="这是一条不会触发 AI 的短动态正文。"),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001,)),
    )

    message = delivery.content_calls[0]["message"]
    assert isinstance(message, OutboundMessage)
    assert message.parts[0] == TextPart("这是一条不会触发 AI 的短动态正文。")


@pytest.mark.asyncio
async def test_full_dynamic_filters_unsubscribed_targets_before_link_and_content(
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery()
    subscriptions = PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite")
    subscription_key = bili_push_subscription_key(1310714247)
    subscriptions.unsubscribe(_group(1001), subscription_key, "bili_push")
    subscriptions.unsubscribe(_private(2001), subscription_key, "bili_push")
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        subscriptions,
    )

    await sender.send(
        _item(include_image=False),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001, 1002), full_users=(2001, 2002)),
    )

    requests = delivery.link_calls[1]["requests"]
    assert isinstance(requests, tuple)
    assert [request.conversation for request in requests] == [
        _group(1002),
        _private(2002),
    ]
    assert delivery.content_calls[0]["conversations"] == (
        _group(1002),
        _private(2002),
    )


@pytest.mark.asyncio
async def test_full_dynamic_delegates_retry_policy_once(
    tmp_path: Path,
) -> None:
    calls: list[tuple[ConversationRef, ...]] = []

    @dataclass
    class _PartiallyFailingDelivery(_RecordingDelivery):
        async def send(
            self,
            message: OutboundMessage,
            conversations: Iterable[ConversationRef],
            **kwargs: object,
        ) -> ProactiveDeliverySummary:
            selected = tuple(conversations)
            self.content_calls.append(
                {"message": message, "conversations": selected, **kwargs}
            )
            calls.append(selected)
            return ProactiveDeliverySummary((_group(1001),), (_private(2001),))

    delivery = _PartiallyFailingDelivery()
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
    )

    await sender.send(
        _item(include_image=False),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001,), full_users=(2001,)),
    )

    assert calls == [(_group(1001), _private(2001))]
    assert [call["action_name"] for call in delivery.content_calls] == [
        FULL_DYNAMIC_PUSH_ACTION,
    ]


@pytest.mark.asyncio
async def test_full_dynamic_media_preferences_filter_text_and_images_separately(
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery()
    subscriptions = PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite")
    uid = 1310714247
    subscriptions.unsubscribe(
        _group(1001),
        bili_media_subscription_key(uid, "image"),
        "bili_push",
    )
    subscriptions.unsubscribe(
        _group(1002),
        bili_media_subscription_key(uid, "text"),
        "bili_push",
    )
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        subscriptions,
    )

    await sender.send(
        _item(),
        PUB_TS,
        uid,
        _targets(full_groups=(1001, 1002)),
    )

    assert delivery.content_calls[0]["conversations"] == (_group(1001),)
    assert delivery.content_calls[1]["conversations"] == (_group(1002),)


def test_image_only_dynamic_does_not_invent_content_text() -> None:
    text = render_dynamic_text_message(_item(text=""))
    images = render_dynamic_image_message(_item(text=""))

    assert text is None
    assert images is not None
    assert isinstance(images.parts[0], RemoteImagePart)


def test_bilibili_admin_hint_is_limited_once_per_group_per_day(
    tmp_path: Path,
) -> None:
    sender = BilibiliDynamicOutboundSender(
        _RecordingDelivery(),  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
    )
    message = OutboundMessage((TextPart("正文"),))

    first = sender._target_link_message(message, _group(1001))
    second = sender._target_link_message(
        OutboundMessage((TextPart("正文2"),)),
        _group(1001),
    )
    other_group = sender._target_link_message(
        OutboundMessage((TextPart("正文3"),)),
        _group(1002),
    )
    private = sender._target_link_message(
        OutboundMessage((TextPart("正文4"),)),
        _private(1),
    )

    assert BILI_PUSH_ADMIN_HINT in _message_text(first)
    assert BILI_PUSH_ADMIN_HINT not in _message_text(second)
    assert BILI_PUSH_ADMIN_HINT in _message_text(other_group)
    assert BILI_PUSH_ADMIN_HINT not in _message_text(private)


def _message_text(message: OutboundMessage) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))
