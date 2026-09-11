from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from pydantic import ValidationError

from ironsbot.app.command_directory.dynamic import configured_message_commands
from ironsbot.config.models.messaging import (
    MessageCommandAction,
    MessageKeywordReplyAction,
    MessageMentionReplyAction,
    MessageScheduledAction,
)
from ironsbot.plugins.messaging import matchers
from ironsbot.runtime.matchers import MatcherRegistry
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.runtime import build_test_runtime
from tests.test_messaging_runtime_setup import _messaging_resources

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State
    from pytest import MonkeyPatch

    from ironsbot.runtime.matchers import CommandPolicy
    from ironsbot.services.messaging.push_time import PushTimeOption
    from ironsbot.services.messaging.service import MessagingService


@pytest.fixture
def installed_messaging(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[list[type[Matcher]], MessagingService]]:
    messaging = _messaging_resources(
        tmp_path / "subscriptions.sqlite",
        commands=[
            MessageCommandAction(
                id="join_group",
                commands=["加群"],
                messages=["加群：202140716"],
                feature="text",
            )
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="keyword",
                keywords=["群"],
                messages=["keyword reply"],
                feature="text",
            )
        ],
        group_policy={"456": ["text"]},
        user_policy={"123": ["text"]},
        mention_replies=[
            MessageMentionReplyAction(
                id="example_mention",
                user_ids=[123],
                messages=["123"],
            )
        ],
    )
    registry = build_test_runtime(
        state_path=tmp_path / "state.sqlite"
    ).matcher_registry()
    registered: list[type[Matcher]] = []
    original = MatcherRegistry.on_message

    def capture(
        self: MatcherRegistry,
        *,
        policy: CommandPolicy,
        **kwargs: object,
    ) -> type[Matcher]:
        matcher = original(self, policy=policy, **kwargs)
        registered.append(matcher)
        return matcher

    async def refresh(_option: PushTimeOption) -> None:
        return

    monkeypatch.setattr(MatcherRegistry, "on_message", capture)
    matchers.install(registry, refresh, messaging, ("messaging.commands",))
    try:
        yield registered, messaging
    finally:
        for matcher in registered:
            matcher.destroy()


@pytest.fixture
def command_runtime(
    installed_messaging: tuple[list[type[Matcher]], MessagingService],
) -> tuple[type[Matcher], MessagingService]:
    registered, messaging = installed_messaging
    return registered[1], messaging


class ReplyRecorder:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.state: T_State = {}

    async def finish(self, message: Message) -> None:
        self.messages.append(message)

    async def send(self, message: Message) -> None:
        self.messages.append(message)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"messages": []},
        {"messages": [" "]},
        {"messages": "one"},
        {"message": "one"},
        {"message": "one", "messages": ["two"]},
    ],
)
@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (MessageCommandAction, {"commands": ["出出三连"]}),
        (MessageKeywordReplyAction, {"keywords": ["出出"]}),
        (MessageMentionReplyAction, {"user_ids": [123]}),
        (MessageScheduledAction, {"time": "23:00"}),
    ],
)
def test_message_actions_reject_missing_or_legacy_messages(
    payload: dict[str, object],
    model: type[
        MessageCommandAction
        | MessageKeywordReplyAction
        | MessageMentionReplyAction
        | MessageScheduledAction
    ],
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"id": "triple_reply", **fields, **payload})


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_fixed_command_sends_each_message_in_order(
    command_runtime: tuple[type[Matcher], MessagingService], *, private: bool
) -> None:
    matcher, messaging = command_runtime
    parts = ["星皇穿了", "咤克斯瞬了", "机盖弹了", "机盖弹了"]
    messaging._config.commands[0] = MessageCommandAction(
        id="join_group", commands=["加群"], messages=parts, at_user_ids=[790]
    )
    event = (
        private_message_event("加群", user_id=123)
        if private
        else group_message_event(message=Message("加群") + MessageSegment.at(789))
    )
    state: T_State = {}
    assert await matcher.rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_message_command(
        cast("Matcher", recorder), event, state, messaging=messaging
    )
    assert [
        message.extract_plain_text().strip() for message in recorder.messages
    ] == parts
    for message in recorder.messages:
        assert [s.data["qq"] for s in message if s.type == "at"] == (
            [] if private else ["789", "790"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("targets", [(), (789,), (789, 790, 789)])
@pytest.mark.parametrize("reply_message_id", [None, 999])
async def test_fixed_command_replies_to_mentions_instead_of_sender(
    command_runtime: tuple[type[Matcher], MessagingService],
    targets: tuple[int, ...],
    reply_message_id: int | None,
) -> None:
    matcher, messaging = command_runtime
    event = group_message_event(
        message=Message(
            [
                MessageSegment.text("加群 "),
                *(MessageSegment.at(target) for target in targets),
            ]
        ),
        reply_message_id=reply_message_id,
    )
    state: T_State = {}
    assert await matcher.rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_message_command(
        cast("Matcher", recorder), event, state, messaging=messaging
    )
    assert len(recorder.messages) == 1
    reply = recorder.messages[0]
    assert [s.data["qq"] for s in reply if s.type == "at"] == [
        str(target) for target in dict.fromkeys(targets or (event.user_id,))
    ]
    assert reply.extract_plain_text().strip() == "加群：202140716"


@pytest.mark.asyncio
async def test_configured_mentions_are_preserved_and_deduplicated(
    command_runtime: tuple[type[Matcher], MessagingService],
) -> None:
    matcher, messaging = command_runtime
    messaging._config.commands[0].at_user_ids = [789, 790]
    event = group_message_event(message=Message("加群") + MessageSegment.at(789))
    state: T_State = {}
    assert await matcher.rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_message_command(
        cast("Matcher", recorder), event, state, messaging=messaging
    )
    assert [s.data["qq"] for s in recorder.messages[0] if s.type == "at"] == [
        "789",
        "790",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        group_message_event(message=Message("想加群") + MessageSegment.at(789)),
        group_message_event(message=Message("加群") + MessageSegment.at("all")),
        group_message_event(message=Message("加群") + MessageSegment.at(1)),
        group_message_event(
            message=Message("加群") + MessageSegment.at(789), group_id=999
        ),
    ],
)
async def test_mentions_do_not_bypass_keyword_or_feature_rules(
    command_runtime: tuple[type[Matcher], MessagingService],
    event: MessageEvent,
) -> None:
    matcher, _ = command_runtime
    assert not await matcher.rule(cast("Bot", None), event, {})


@pytest.mark.asyncio
async def test_private_reply_stays_plain_text(
    command_runtime: tuple[type[Matcher], MessagingService],
) -> None:
    matcher, messaging = command_runtime
    event = private_message_event("加群", user_id=123)
    state: T_State = {}
    assert await matcher.rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_message_command(
        cast("Matcher", recorder), event, state, messaging=messaging
    )
    assert str(recorder.messages[0]) == "加群：202140716"


@pytest.mark.asyncio
async def test_keyword_reply_sends_messages_in_order(
    command_runtime: tuple[type[Matcher], MessagingService],
) -> None:
    matcher, messaging = command_runtime
    messaging._config.keyword_replies[0].messages = ["first", "second"]
    event = group_message_event("测试群回复")
    state: T_State = {}
    assert await matcher.rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_message_command(
        cast("Matcher", recorder), event, state, messaging=messaging
    )
    assert [str(message) for message in recorder.messages] == [
        "[CQ:at,qq=123] first", "[CQ:at,qq=123] second"
    ]


@pytest.mark.asyncio
async def test_personal_mention_sends_messages_in_order(
    installed_messaging: tuple[list[type[Matcher]], MessagingService],
) -> None:
    registered, messaging = installed_messaging
    messaging._config.mention_replies[0].messages = ["first", "second"]
    event = group_message_event(message=Message(MessageSegment.at(1)))
    state: T_State = {}
    assert await registered[0].rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_group_mention_reply(cast("Matcher", recorder), event, state)
    assert [str(message) for message in recorder.messages] == [
        "[CQ:at,qq=123] first", "[CQ:at,qq=123] second"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_message_id", [None, 999])
async def test_personal_mention_works_without_group_features_and_replies_to_sender(
    installed_messaging: tuple[list[type[Matcher]], MessagingService],
    reply_message_id: int | None,
) -> None:
    registered, messaging = installed_messaging
    matcher = registered[0]
    event = group_message_event(
        message=MessageSegment.at(1) + Message(" hello"),
        group_id=999,
        reply_message_id=reply_message_id,
    )
    state: T_State = {}
    assert await matcher.rule(cast("Bot", None), event, state)
    recorder = ReplyRecorder()
    await matchers.handle_group_mention_reply(cast("Matcher", recorder), event, state)
    assert str(recorder.messages[0]) == "[CQ:at,qq=123] 123"
    assert matcher.block
    assert not any(
        "mention_reply" in item.id
        for item in configured_message_commands(messaging._config)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        group_message_event(message=Message(MessageSegment.at(1)), user_id=789),
        group_message_event(message=Message(MessageSegment.at(789))),
        group_message_event("hello"),
        private_message_event("hello"),
    ],
)
async def test_personal_mention_does_not_capture_other_input(
    installed_messaging: tuple[list[type[Matcher]], MessagingService],
    event: MessageEvent,
) -> None:
    registered, _ = installed_messaging
    assert not await registered[0].rule(cast("Bot", None), event, {})


@pytest.mark.asyncio
async def test_personal_mention_can_be_disabled(
    installed_messaging: tuple[list[type[Matcher]], MessagingService],
) -> None:
    registered, messaging = installed_messaging
    messaging._config.mention_replies[0].enabled = False
    event = group_message_event(message=Message(MessageSegment.at(1)))
    assert not await registered[0].rule(cast("Bot", None), event, {})


@pytest.mark.parametrize("policy", ["group", "user"])
def test_personal_mention_respects_blacklists(tmp_path: Path, policy: str) -> None:
    messaging = _messaging_resources(
        tmp_path / "subscriptions.sqlite",
        mention_replies=[
            MessageMentionReplyAction(
                id="example_mention",
                user_ids=[123],
                messages=["123"],
            )
        ],
        group_policy={"456": ["blacklist"]} if policy == "group" else {},
        user_policy={"123": ["blacklist"]} if policy == "user" else {},
    )
    assert messaging.match_group_mention_reply(user_id=123, group_id=456) is None


def test_personal_mention_model_rejects_obsolete_feature() -> None:
    with pytest.raises(ValidationError, match="feature"):
        MessageMentionReplyAction.model_validate(
            {
                "id": "example_mention",
                "user_ids": [123],
                "message": "123",
                "feature": "text",
            }
        )
