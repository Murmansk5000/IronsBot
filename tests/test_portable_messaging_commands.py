from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.messaging.push_time import PushTimeOption
    from ironsbot.services.portable_reply import PortableReply

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import (
    MessageCommandAction,
    MessageConfig,
    MessageScheduledAction,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig
from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    TextPart,
)
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.identity_link_store import OfficialIdentity
from ironsbot.services.identity_principals import IdentityPrincipalService
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


def _group_context(
    text: str,
    *mentions: ActorRef,
) -> MessageInputContext:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "sender-openid",
        kind="member",
        scope_id="group-openid",
        account_id="app-id",
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                "group-openid",
                account_id="app-id",
            ),
            message_id="message-id",
            text=text,
            direct_mentions=mentions,
        ),
        mentions_bot=False,
    )


@pytest.mark.asyncio
async def test_portable_text_commands_include_configured_mention_targets() -> None:
    messaging = MessagingService(
        MessageConfig(
            commands=[
                MessageCommandAction(
                    id="portable",
                    commands=["链接"],
                    messages=["第一条", "https://example.test"],
                ),
                MessageCommandAction(
                    id="onebot-only",
                    commands=["提醒"],
                    messages=["提醒内容"],
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
        "messaging.onebot-only",
        "messaging.push_subscription",
    }
    result = cast(
        "PortableReply",
        await operations["messaging.portable"]("链接", _context("链接")),
    )
    assert cast("TextPart", result.message.parts[0]).text == "第一条"
    assert len(result.additional_messages) == 1
    assert (
        cast("TextPart", result.additional_messages[0].parts[0]).text
        == "https://example.test"
    )


@pytest.mark.asyncio
async def test_official_configured_mention_requires_verified_member() -> None:
    qq_actor = ActorRef(Platform.ONEBOT, "123456789")
    principals = IdentityPrincipalService()
    messaging = MessagingService(
        MessageConfig(
            commands=[
                MessageCommandAction(
                    id="notice",
                    commands=["提醒"],
                    messages=["提醒内容"],
                    at_user_ids=[123456789],
                )
            ]
        ),
        ActivityConfig(),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", object()),
        _command_mentions={"notice": (qq_actor,)},
    )
    operation = build_portable_messaging_operations(
        messaging,
        PortableQuerySessions(),
        identity_principals=principals,
    )["messaging.notice"]

    unresolved = cast("PortableReply", await operation("提醒", _group_context("提醒")))
    assert "未发送" in cast("TextPart", unresolved.message.parts[0]).text

    principals.register_official_link(
        onebot_qq_id=qq_actor.id,
        official=OfficialIdentity("app-id", "member", "target-openid"),
    )
    resolved = cast("PortableReply", await operation("提醒", _group_context("提醒")))
    assert resolved.message.parts[0] == MentionPart(
        ActorRef(
            Platform.QQ_OFFICIAL,
            "target-openid",
            "member",
            "group-openid",
            account_id="app-id",
        )
    )


@pytest.mark.asyncio
async def test_portable_text_command_addresses_explicit_member_targets() -> None:
    messaging = MessagingService(
        MessageConfig(
            commands=[
                MessageCommandAction(
                    id="portable",
                    commands=["链接"],
                    messages=["第一条", "第二条"],
                )
            ]
        ),
        ActivityConfig(),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", object()),
    )
    target = ActorRef(
        Platform.QQ_OFFICIAL,
        "target-openid",
        kind="member",
        scope_id="group-openid",
        account_id="app-id",
    )

    result = cast(
        "PortableReply",
        await build_portable_messaging_operations(
            messaging,
            PortableQuerySessions(),
        )["messaging.portable"]("链接", _group_context("链接", target, target)),
    )

    assert result.message.parts == (
        MentionPart(target),
        TextPart(" "),
        TextPart("第一条"),
    )
    assert result.additional_messages[0].parts == (
        MentionPart(target),
        TextPart(" "),
        TextPart("第二条"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("demote", [False, True])
@pytest.mark.parametrize("button", [False, True])
async def test_portable_subscription_menu_persists_qq_official_openid(
    tmp_path: Path,
    *,
    demote: bool,
    button: bool,
) -> None:
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore

    context = _context("TD")
    if demote:
        context = replace(
            context,
            message=replace(
                context.message,
                conversation=ConversationRef(
                    Platform.QQ_OFFICIAL, "group", "test-group"
                ),
                group_role="admin",
            ),
        )
    conversation = context.message.conversation
    actor = context.message.actor
    store = PushUnsubscribeStore(tmp_path / "qq_state.sqlite")
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        store,
        FeatureService(
            {conversation: frozenset({"seer_activity_push"})} if demote else {},
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

    selection_context = replace(
        context, message=replace(context.message, group_role="member")
    )
    assert menu.prompt is not None
    assert menu.prompt is sessions.active_prompt(context)
    selection = menu.prompt.action_data(menu.prompt.choices[0]) if button else "1"
    result = await sessions.select(selection, selection_context)
    assert result is not None
    expected = "普通群成员只能查看" if demote else "已退订：活动结束提醒"
    assert expected in cast("TextPart", result.parts[0]).text
    assert store.is_unsubscribed(conversation, "seer_activity_push") is not demote
    assert result.prompt is sessions.active_prompt(selection_context)
    assert result.prompt is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("demote_at", ["never", "menu", "input"])
@pytest.mark.parametrize("button", [False, True])
async def test_portable_push_time_updates_qq_official_conversation(
    tmp_path: Path,
    demote_at: str,
    *,
    button: bool,
) -> None:
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore

    context = _context("推送时间")
    if demote_at != "never":
        context = replace(
            context,
            message=replace(
                context.message,
                conversation=ConversationRef(
                    Platform.QQ_OFFICIAL, "group", "test-group"
                ),
                group_role="admin",
            ),
        )
    actor = context.message.actor
    store = PushUnsubscribeStore(tmp_path / "qq_state.sqlite")
    messaging = MessagingService(
        MessageConfig(
            schedules=[
                MessageScheduledAction(
                    id="daily",
                    name="每日消息",
                    messages=["消息"],
                    time="23:00",
                )
            ]
        ),
        ActivityConfig(),
        store,
        FeatureService(
            {context.message.conversation: frozenset({"text_push"})},
            {actor: frozenset({"text_push"})},
            frozenset(),
        ),
        cast("Any", object()),
        cast("Any", object()),
    )
    refreshed: list[str] = []

    async def refresh(option: PushTimeOption) -> None:
        refreshed.append(option.key)

    sessions = PortableQuerySessions()
    operations = build_portable_messaging_operations(
        messaging,
        sessions,
        refresh_push_time_jobs=refresh,
    )

    menu = cast(
        "OutboundMessage",
        await operations["messaging.push_time"]("推送时间", context),
    )
    assert "每日消息" in cast("TextPart", menu.parts[0]).text
    assert menu.prompt is not None
    assert menu.prompt is sessions.active_prompt(context)
    selection = menu.prompt.action_data(menu.prompt.choices[0]) if button else "1"
    member = replace(context, message=replace(context.message, group_role="member"))
    value_prompt = await sessions.select(
        selection, member if demote_at == "menu" else context
    )
    assert value_prompt is not None
    if demote_at == "menu":
        assert "不能修改推送时间" in cast("TextPart", value_prompt.parts[0]).text
        assert not sessions.has_active_session(member)
        assert not refreshed
        return
    assert "HH:MM" in cast("TextPart", value_prompt.parts[0]).text
    assert sessions.recognizes_response("21:30", context)
    result = await sessions.select("21:30", member if demote_at == "input" else context)

    assert result is not None
    if demote_at == "input":
        assert "不能修改推送时间" in cast("TextPart", result.parts[0]).text
        assert (
            messaging.push_time_options(context.message.conversation)[0].current_value
            != "21:30:00"
        )
        assert not refreshed
        return
    assert "已设置：每日消息" in cast("TextPart", result.parts[0]).text
    current = messaging.push_time_options(context.message.conversation)[0].current_value
    assert current == "21:30:00"
    assert len(refreshed) == 1
    assert result.prompt is not None
    assert result.prompt is sessions.active_prompt(context)


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
