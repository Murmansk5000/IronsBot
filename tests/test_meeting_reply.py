from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from ironsbot.core.features import FeatureConfig
from ironsbot.plugins.messaging import meeting
from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.services.messaging.meeting import build_meeting_reply
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher

    from ironsbot.runtime.matchers import CommandPolicy


@pytest.fixture
def meeting_matcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[type[Matcher]]:
    runtime = build_test_runtime(
        state_path=tmp_path / "state.sqlite",
        feature_config=FeatureConfig(
            group_policy={"456": ["meeting"]},
            user_policy={"123": ["meeting"]},
        ),
    )
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

    monkeypatch.setattr(MatcherRegistry, "on_message", capture)
    meeting.install(
        runtime.matcher_registry(),
        ("会议", "开播"),
        "6638682008",
        "会议号：{meeting_number}",
        runtime.features,
    )
    try:
        yield registered[0]
    finally:
        for matcher in registered:
            matcher.destroy()


class _ReplyRecorder:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.state: dict[str, object] = {}

    async def finish(self, message: Message) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["会议", "开播"])
@pytest.mark.parametrize("targets", [(), (789,), (789, 790, 789)])
@pytest.mark.parametrize("reply_message_id", [None, 999])
async def test_meeting_replies_to_mentioned_members(
    meeting_matcher: type[Matcher],
    command: str,
    targets: tuple[int, ...],
    reply_message_id: int | None,
) -> None:
    event = group_message_event(
        message=Message(
            [MessageSegment.text(command), *(MessageSegment.at(x) for x in targets)]
        ),
        reply_message_id=reply_message_id,
    )
    assert await meeting_matcher.rule(cast("Bot", None), event, {})
    recorder = _ReplyRecorder()
    await meeting_matcher.handlers[-1].call(matcher=recorder, event=event)
    assert len(recorder.messages) == 1
    message = recorder.messages[0]
    assert [s.data["qq"] for s in message if s.type == "at"] == [
        str(x) for x in dict.fromkeys(targets or (event.user_id,))
    ]
    assert message.extract_plain_text().strip() == "会议号：663-868-2008"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        group_message_event(message=Message("会议") + MessageSegment.at("all")),
        group_message_event(message=Message("会议") + MessageSegment.at(1)),
        group_message_event(
            message=Message("会议") + MessageSegment.at(789), group_id=999
        ),
        group_message_event(message=Message("快来会议") + MessageSegment.at(789)),
    ],
)
async def test_meeting_mentions_do_not_bypass_input_or_feature_rules(
    meeting_matcher: type[Matcher],
    event: MessageEvent,
) -> None:
    assert not await meeting_matcher.rule(cast("Bot", None), event, {})


@pytest.mark.asyncio
async def test_meeting_private_reply_stays_plain_text(
    meeting_matcher: type[Matcher],
) -> None:
    event = private_message_event("会议", user_id=123)
    assert await meeting_matcher.rule(cast("Bot", None), event, {})
    recorder = _ReplyRecorder()
    await meeting_matcher.handlers[-1].call(matcher=recorder, event=event)
    assert str(recorder.messages[0]) == "会议号：663-868-2008"


def test_build_meeting_reply_returns_none_without_number() -> None:
    assert build_meeting_reply("", "{meeting_number}") is None


def test_build_meeting_reply_formats_tencent_meeting_number() -> None:
    reply = build_meeting_reply(
        "6638682008",
        ("会议号：{meeting_number}\n数字：{meeting_digits}\n链接：{meeting_url}"),
    )

    assert reply == (
        "会议号：663-868-2008\n"
        "数字：6638682008\n"
        "链接：https://meeting.tencent.com/p/6638682008"
    )
