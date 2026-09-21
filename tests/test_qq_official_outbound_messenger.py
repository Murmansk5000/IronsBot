from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.interactive_prompts import PromptChoice, PromptSession
from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    MentionPart,
    OutboundMessage,
    ReplyContext,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialTextPayload,
)
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.integrations.qq_official.recipient_state import (
    QQOfficialRecipientStateStore,
)
from ironsbot.services.messaging.outbound_routing import PlatformOutboundMessenger

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.integrations.qq_official.message_rendering import QQOfficialPayload


@dataclass
class _Bot:
    response_id: str | None = "message-1"
    calls: list[
        tuple[str, str, tuple[QQOfficialPayload, ...], str | None, int | None]
    ] = field(default_factory=list)

    async def send_to_c2c(
        self,
        openid: str,
        payloads: tuple[QQOfficialPayload, ...],
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object:
        self.calls.append(("private", openid, payloads, msg_id, msg_seq))
        return SimpleNamespace(id=self.response_id)

    async def send_to_group(
        self,
        group_openid: str,
        payloads: tuple[QQOfficialPayload, ...],
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object:
        self.calls.append(("group", group_openid, payloads, msg_id, msg_seq))
        return SimpleNamespace(id=self.response_id)


@dataclass
class _UnexpectedMessenger:
    send_calls: int = 0

    async def send(
        self,
        _conversation: ConversationRef,
        _message: OutboundMessage,
    ) -> object:
        self.send_calls += 1
        raise AssertionError


GROUP = ConversationRef(
    Platform.QQ_OFFICIAL,
    "group",
    "group-openid",
    account_id="app",
)
PRIVATE = ConversationRef(
    Platform.QQ_OFFICIAL,
    "private",
    "user-openid",
    account_id="app",
)
TEXT = OutboundMessage.from_text("result")
FUTURE_DEADLINE = datetime(2099, 1, 1, tzinfo=UTC)


def _reply(
    conversation: ConversationRef,
    message_id: str,
    sequence: str | None = None,
) -> ReplyContext:
    return ReplyContext(
        conversation,
        message_id,
        sequence,
        reply_deadline=FUTURE_DEADLINE,
    )


@pytest.mark.asyncio
async def test_proactive_delivery_is_explicitly_disabled_by_default() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.send(GROUP, TEXT)

    assert not messenger.capabilities_for(GROUP).can_send_proactively
    assert result.error_code == "proactive_disabled"
    assert result.failure_kind is DeliveryFailureKind.PERMANENT
    assert bot.calls == []


@pytest.mark.asyncio
async def test_proactive_delivery_respects_persisted_recipient_rejection(
    tmp_path: Path,
) -> None:
    bot = _Bot()
    state = QQOfficialRecipientStateStore(tmp_path / "state.sqlite")
    await state.record_event(
        app_id="app",
        event_type="GROUP_MSG_REJECT",
        raw={"group_openid": GROUP.id},
    )
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: bot,
        recipient_state=state,
    )

    result = await messenger.send(GROUP, TEXT)

    assert result.error_code == "recipient_rejected"
    assert result.failure_kind is DeliveryFailureKind.PERMANENT
    assert bot.calls == []

    passive = await messenger.reply(_reply(GROUP, "event-id"), TEXT)
    assert passive.delivered
    assert len(bot.calls) == 1


def test_custom_keyboard_capability_is_account_scoped() -> None:
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: _Bot(),
        account_custom_keyboards={"app": True},
    )

    assert messenger.capabilities_for(GROUP).supports_interactive_prompts
    assert messenger.capabilities_for(PRIVATE).supports_interactive_prompts
    other_account = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        GROUP.id,
        account_id="other-app",
    )
    assert not messenger.capabilities_for(other_account).supports_interactive_prompts


def test_member_mentions_are_supported_only_in_owned_group_conversations() -> None:
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: _Bot(),
    )

    assert messenger.capabilities_for(GROUP).can_mention_members
    assert not messenger.capabilities_for(PRIVATE).can_mention_members


def _image_prompt() -> PromptSession:
    return PromptSession(
        "menu",
        ActorRef(
            Platform.QQ_OFFICIAL,
            "member-openid",
            "member",
            GROUP.id,
            account_id="app",
        ),
        GROUP,
        "event-id",
        (PromptChoice("1", "第一项", frozenset({"1"})),),
        4_102_444_800.0,
    )


@pytest.mark.asyncio
async def test_image_prompt_does_not_require_text_without_keyboard_capability() -> None:
    bot = _Bot()
    prompt = _image_prompt()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.reply(
        _reply(GROUP, "event-id"),
        OutboundMessage((BinaryImagePart(b"image", "image/png"),), prompt=prompt),
    )

    assert result.delivered
    assert bot.calls[0][2] == (
        QQOfficialImagePayload(content=b"image", filename="ironsbot.png"),
    )


@pytest.mark.asyncio
async def test_image_prompt_adds_one_keyboard_text_payload_when_enabled() -> None:
    bot = _Bot()
    prompt = _image_prompt()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
        account_custom_keyboards={"app": True},
    )

    result = await messenger.reply(
        _reply(GROUP, "event-id"),
        OutboundMessage((BinaryImagePart(b"image", "image/png"),), prompt=prompt),
    )

    assert result.delivered
    payloads = bot.calls[0][2]
    assert payloads == (
        QQOfficialImagePayload(content=b"image", filename="ironsbot.png"),
        QQOfficialTextPayload(
            "请选择：\n1. 第一项\n\n回复序号选择",
            prompt=prompt,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conversation", "kind"),
    [(GROUP, "group"), (PRIVATE, "private")],
)
async def test_enabled_proactive_delivery_uses_conversation_target(
    conversation: ConversationRef,
    kind: str,
) -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.send(conversation, TEXT)

    assert result.delivered
    assert bot.calls[0][0:2] == (kind, conversation.id)
    assert bot.calls[0][3:] == (None, None)


@pytest.mark.asyncio
async def test_account_scoped_conversation_uses_its_matching_bot() -> None:
    bot = _Bot()
    requested_accounts: list[str] = []
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda account_id: requested_accounts.append(account_id) or bot,
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        account_id="app",
    )

    result = await messenger.send(conversation, TEXT)

    assert result.delivered
    assert requested_accounts == ["app"]


@pytest.mark.asyncio
async def test_single_account_messenger_rejects_another_bot_account() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app-a": True},
        bot_provider=lambda _app_id: bot,
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        account_id="app-b",
    )

    result = await messenger.send(conversation, TEXT)

    assert not messenger.capabilities_for(conversation).can_send_proactively
    assert result.error_code == "account_mismatch"
    assert bot.calls == []


@pytest.mark.asyncio
async def test_multi_account_delivery_uses_own_bot_and_policy() -> None:
    bots = {"app-a": _Bot(), "app-b": _Bot()}
    messenger = QQOfficialOutboundMessenger(
        {"app-a": False, "app-b": True},
        bot_provider=bots.get,
    )
    target_a = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "same-openid",
        account_id="app-a",
    )
    target_b = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "same-openid",
        account_id="app-b",
    )

    rejected = await messenger.send(target_a, TEXT)
    delivered = await messenger.send(target_b, TEXT)

    assert rejected.error_code == "proactive_disabled"
    assert delivered.delivered
    assert bots["app-a"].calls == []
    assert bots["app-b"].calls[0][1] == "same-openid"


@pytest.mark.asyncio
async def test_reply_sequences_are_isolated_by_bot_account() -> None:
    bots = {"app-a": _Bot(), "app-b": _Bot()}
    messenger = QQOfficialOutboundMessenger(
        {"app-a": False, "app-b": False},
        bot_provider=bots.get,
    )

    for account_id in bots:
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            "same-openid",
            account_id=account_id,
        )
        result = await messenger.reply(
            _reply(conversation, "same-message-id"),
            TEXT,
        )
        assert result.delivered

    assert bots["app-a"].calls[0][4] == 1
    assert bots["app-b"].calls[0][4] == 1


@pytest.mark.asyncio
async def test_accountless_official_target_is_rejected() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: bot,
    )
    target = ConversationRef(Platform.QQ_OFFICIAL, "private", "openid")

    result = await messenger.send(target, TEXT)

    assert result.error_code == "account_mismatch"
    assert bot.calls == []


@pytest.mark.asyncio
async def test_reply_uses_event_message_id_and_first_reply_sequence() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.reply(_reply(GROUP, "event-id", "event-index"), TEXT)

    assert result.delivered
    assert bot.calls[0][3:] == ("event-id", 1)


@pytest.mark.asyncio
async def test_group_reply_references_inbound_message_index() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.reply(
        _reply(GROUP, "event-id", "source-message-index"),
        TEXT,
    )

    assert result.delivered
    assert messenger.capabilities_for(GROUP).can_mention_members
    assert bot.calls[0][2] == (
        QQOfficialTextPayload("result", reference_id="source-message-index"),
    )


@pytest.mark.asyncio
async def test_group_member_mention_is_one_markdown_passive_reply() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        GROUP.id,
        account_id="app",
    )

    result = await messenger.reply(
        _reply(GROUP, "event-id", "source-message-index"),
        OutboundMessage((MentionPart(member), TextPart(" result"))),
    )

    assert result.delivered
    assert bot.calls[0][2] == (
        QQOfficialTextPayload(
            '<qqbot-at-user id="member-openid" />\n\nresult',
            markdown=True,
        ),
    )
    assert bot.calls[0][3:] == ("event-id", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context", "error_code"),
    [
        (ReplyContext(GROUP, "event-id"), "passive_reply_deadline_missing"),
        (
            ReplyContext(
                GROUP,
                "event-id",
                reply_deadline=datetime(2000, 1, 1, tzinfo=UTC),
            ),
            "passive_reply_expired",
        ),
    ],
)
async def test_invalid_passive_reply_window_fails_before_transport(
    context: ReplyContext,
    error_code: str,
) -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.reply(context, TEXT)

    assert result.error_code == error_code
    assert bot.calls == []


@pytest.mark.asyncio
async def test_same_message_id_is_isolated_by_conversation() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )
    other_group = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "other-group",
        account_id="app",
    )

    assert (await messenger.reply(_reply(GROUP, "event-id"), TEXT)).delivered
    assert (await messenger.reply(_reply(other_group, "event-id"), TEXT)).delivered

    assert [call[4] for call in bot.calls] == [1, 1]


@pytest.mark.asyncio
async def test_replies_allocate_unique_sequences_per_event() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": False},
        bot_provider=lambda _app_id: bot,
    )

    for _ in range(5):
        assert (await messenger.reply(_reply(GROUP, "event-id"), TEXT)).delivered
    exhausted = await messenger.reply(_reply(GROUP, "event-id"), TEXT)
    other = await messenger.reply(_reply(GROUP, "other-event"), TEXT)

    assert [call[4] for call in bot.calls] == [1, 2, 3, 4, 5, 1]
    assert exhausted.error_code == "passive_reply_limit_exceeded"
    assert other.delivered


@pytest.mark.asyncio
async def test_reply_limit_can_fall_back_to_explicitly_enabled_proactive_send() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: bot,
    )

    for _ in range(5):
        result = await messenger.reply(_reply(PRIVATE, "event-id"), TEXT)
        assert result.delivered

    assert [call[3:] for call in bot.calls] == [
        ("event-id", 1),
        ("event-id", 2),
        ("event-id", 3),
        ("event-id", 4),
        (None, None),
    ]


@pytest.mark.asyncio
async def test_unavailable_bot_is_reported_without_attempting_delivery() -> None:
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: None,
    )

    result = await messenger.send(GROUP, TEXT)

    assert result.error_code == "bot_unavailable"
    assert result.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE


@pytest.mark.asyncio
async def test_missing_response_id_is_an_uncertain_delivery() -> None:
    bot = _Bot(response_id=None)
    messenger = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.send(GROUP, TEXT)

    assert result.error_code == "missing_message_id"
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN


@pytest.mark.asyncio
async def test_platform_router_delegates_and_rejects_missing_adapter() -> None:
    bot = _Bot()
    official = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: bot,
    )
    routed = PlatformOutboundMessenger({Platform.QQ_OFFICIAL: official})
    unsupported = ConversationRef(Platform.ONEBOT, "group", "123")

    delivered = await routed.send(GROUP, TEXT)
    rejected = await routed.send(unsupported, TEXT)

    assert delivered.delivered
    assert rejected.error_code == "unsupported_platform"
    assert rejected.failure_kind is DeliveryFailureKind.PERMANENT


@pytest.mark.asyncio
async def test_official_failure_never_falls_back_to_onebot() -> None:
    official = QQOfficialOutboundMessenger(
        {"app": True},
        bot_provider=lambda _app_id: None,
    )
    onebot = _UnexpectedMessenger()
    routed = PlatformOutboundMessenger(
        {
            Platform.QQ_OFFICIAL: cast("OutboundMessenger", official),
            Platform.ONEBOT: cast("OutboundMessenger", onebot),
        }
    )

    result = await routed.send(GROUP, TEXT)

    assert result.error_code == "bot_unavailable"
    assert result.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
    assert onebot.send_calls == 0
