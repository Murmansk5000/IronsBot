from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import MessageCommandAction, MessageConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.messaging.sendpic import SendpicService
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
    build_portable_sendpic_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions


class _MemoryImages:
    async def count(self, path: str = "") -> int:
        assert path == "gallery"
        return 2

    async def get_file(self, file_path: str) -> bytes:
        return file_path.encode()


def _context(text: str) -> MessageInputContext:
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user")
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id),
            message_id="message-id",
            text=text,
        ),
        mentions_bot=False,
    )


@pytest.mark.asyncio
async def test_portable_text_commands_exclude_onebot_mention_targets() -> None:
    messaging = MessagingService(
        MessageConfig(
            commands=[
                MessageCommandAction(
                    id="portable",
                    commands=["链接"],
                    message="https://example.test",
                ),
                MessageCommandAction(
                    id="onebot-only",
                    commands=["提醒"],
                    message="提醒内容",
                    at_user_ids=[123456],
                ),
            ]
        ),
        ActivityConfig(),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", object()),
    )

    operations = build_portable_messaging_operations(
        messaging,
        PortableQuerySessions(),
    )

    assert set(operations) == {
        "messaging.portable",
        "messaging.push_subscription",
    }
    result = cast(
        "OutboundMessage",
        await operations["messaging.portable"]("链接", _context("链接")),
    )
    assert cast("TextPart", result.parts[0]).text == "https://example.test"


@pytest.mark.asyncio
async def test_portable_subscription_menu_persists_qq_official_openid(
    tmp_path: Path,
) -> None:
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore

    context = _context("TD")
    conversation = context.message.conversation
    actor = context.message.actor
    store = PushUnsubscribeStore(tmp_path / "qq_state.sqlite")
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        store,
        FeatureService(
            {},
            {actor: frozenset({"seer_activity_push"})},
            frozenset(),
        ),
        cast("Any", object()),
        cast("Any", object()),
    )
    sessions = PortableQuerySessions()
    operation = build_portable_messaging_operations(messaging, sessions)[
        "messaging.push_subscription"
    ]

    menu = cast("OutboundMessage", await operation("TD", context))
    assert "活动结束提醒" in cast("TextPart", menu.parts[0]).text

    result = await sessions.select("1", context)
    assert result is not None
    assert "已退订：活动结束提醒" in cast("TextPart", result.parts[0]).text
    assert store.is_unsubscribed(conversation, "seer_activity_push")


@pytest.mark.asyncio
async def test_portable_sendpic_commands_reuse_shared_image_service() -> None:
    single = PicConfig(
        id="single",
        backend="local",
        command="单图",
        mode="single",
        image_file="one.png",
    )
    indexed = PicConfig(
        id="gallery",
        backend="local",
        command="图库",
        mode="indexed",
        image_dir="gallery",
        image_filename_template="{index}.png",
        message_template="{image}\n{index}/{total}",
    )
    service = SendpicService(
        SendpicBehaviorConfig(configs=[single, indexed]),
        lambda _kind: _MemoryImages(),
        command_starts=("/", ""),
    )
    operations = build_portable_sendpic_operations(service)

    single_result = cast(
        "OutboundMessage",
        await operations["sendpic.single"]("单图", _context("单图")),
    )
    indexed_result = cast(
        "OutboundMessage",
        await operations["sendpic.gallery"](
            "图库2",
            _context("/图库2"),
        ),
    )

    assert cast("BinaryImagePart", single_result.parts[0]).content == b"one.png"
    assert isinstance(indexed_result.parts[0], BinaryImagePart)
    assert cast("BinaryImagePart", indexed_result.parts[0]).content == b"gallery/2.png"
    assert "2/2" in "".join(
        part.text for part in indexed_result.parts if isinstance(part, TextPart)
    )


@pytest.mark.asyncio
async def test_portable_sendpic_reports_out_of_range_index() -> None:
    indexed = PicConfig(
        id="gallery",
        backend="local",
        command="图库",
        mode="indexed",
        image_dir="gallery",
        image_filename_template="{index}.png",
    )
    service = SendpicService(
        SendpicBehaviorConfig(configs=[indexed]),
        lambda _kind: _MemoryImages(),
        command_starts=("/", ""),
    )

    result = cast(
        "OutboundMessage",
        await build_portable_sendpic_operations(service)["sendpic.gallery"](
            "图库3",
            _context("图库3"),
        ),
    )

    assert cast("TextPart", result.parts[0]).text == "编号必须在1到2之间！"
