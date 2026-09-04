from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from ironsbot.config.models.messaging import (
    MessageCommandAction,
    MessageKeywordReplyAction,
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
def command_runtime(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[type[Matcher], MessagingService]]:
    messaging = _messaging_resources(
        tmp_path / "subscriptions.sqlite",
        commands=[
            MessageCommandAction(
                id="join_group",
                commands=["加群"],
                message="加群：202140716",
                feature="text",
            )
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="keyword",
                keywords=["群"],
                message="keyword reply",
                feature="text",
            )
        ],
        group_policy={"456": ["text"]},
        user_policy={"123": ["text"]},
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
        yield registered[1], messaging
    finally:
        for matcher in registered:
            matcher.destroy()


class ReplyRecorder:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.state: T_State = {}

    async def finish(self, message: Message) -> None:
        self.messages.append(message)


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
