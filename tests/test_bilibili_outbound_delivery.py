from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.core.outbound import OutboundMessage, RemoteImagePart, TextPart
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.bilibili.outbound_delivery import (
    BILI_PUSH_ADMIN_HINT,
    DYNAMIC_HISTORY_HINT,
    FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS,
    FULL_DYNAMIC_PUSH_ACTION,
    LINK_DYNAMIC_PUSH_ACTION,
    BilibiliDynamicOutboundSender,
    render_dynamic_content_message,
    render_dynamic_link_message,
)
from ironsbot.services.bilibili.targets import BiliPushTargets
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryRequest,
    ProactiveDeliverySummary,
)

if TYPE_CHECKING:
    from pathlib import Path


PUB_TS = 1781004683


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
                        "pics": [
                            {"url": "http://i0.hdslb.com/bfs/new_dyn/test.jpg]"}
                        ],
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
        requests: object,
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
        message: object,
        conversations: object,
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
    content = render_dynamic_content_message(_item())

    assert link is not None
    assert content is not None
    assert "传送门：" in str(link.parts[0])
    assert "正文内容" in str(content.parts[0])
    assert isinstance(content.parts[1], RemoteImagePart)
    assert content.parts[1].url == "http://i0.hdslb.com/bfs/new_dyn/test.jpg"


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
    assert len(delivery.content_calls) == 1
    full_link = delivery.link_calls[1]["requests"]
    assert isinstance(full_link, tuple)
    message = full_link[0].message
    text = "".join(
        part.text for part in message.parts if isinstance(part, TextPart)
    )
    assert DYNAMIC_HISTORY_HINT in text
    assert BILI_PUSH_ADMIN_HINT in text
    assert "传送门：" in text
    content = delivery.content_calls[0]["message"]
    assert isinstance(content, OutboundMessage)
    assert "正文内容" in content.parts[0].text
    assert not delivery.content_calls[0].get("subscription_key")


@pytest.mark.asyncio
async def test_content_retries_failed_conversations_and_notifies_admins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    delivery = _RecordingDelivery(content_failures=FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS)
    admin_notices = _RecordingAdminNotices()

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "ironsbot.services.bilibili.outbound_delivery.asyncio.sleep",
        no_sleep,
    )
    sender = BilibiliDynamicOutboundSender(
        delivery,  # type: ignore[arg-type]
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        admin_notices=admin_notices,  # type: ignore[arg-type]
    )

    await sender.send(
        _item(),
        PUB_TS,
        1310714247,
        _targets(full_groups=(1001,), full_users=(2001,)),
    )

    assert len(delivery.content_calls) == FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS
    assert len(admin_notices.messages) == 1
    message, kwargs = admin_notices.messages[0]
    assert "群：1001" in message
    assert "私聊：2001" in message
    assert kwargs["action_name"] == "Bilibili dynamic content delivery failure"
