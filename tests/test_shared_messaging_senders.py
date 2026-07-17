import asyncio
from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import Message
from pytest import MonkeyPatch

from ironsbot.shared.messaging import senders
from ironsbot.shared.messaging.outbound_rate_limit import OutboundRateLimitDecision
from ironsbot.shared.messaging.senders import send_target_messages
from ironsbot.shared.messaging.targets import MessageTarget

GROUP_ID = 10
PRIVATE_USER_ID = 20
MENTION_USER_ID = 30


class FakeSendError(RuntimeError):
    pass


@dataclass
class FakeBot:
    self_id: int = 0
    failed_group_ids: set[int] = field(default_factory=set)
    private_messages: list[tuple[int, Message]] = field(default_factory=list)
    group_messages: list[tuple[int, Message]] = field(default_factory=list)

    async def send_private_msg(self, *, user_id: int, message: Message) -> None:
        self.private_messages.append((user_id, message))

    async def send_group_msg(self, *, group_id: int, message: Message) -> None:
        if group_id in self.failed_group_ids:
            raise FakeSendError

        self.group_messages.append((group_id, message))


def test_send_target_messages_dedupes_and_limits_by_group() -> None:
    bot = FakeBot()
    limiter_calls: list[int | None] = []

    def _limit(message: str | Message, group_id: int | None) -> str | Message:
        limiter_calls.append(group_id)
        return f"{message}:group={group_id}"

    summary = asyncio.run(
        send_target_messages(
            [
                MessageTarget("group", GROUP_ID, (MENTION_USER_ID,)),
                MessageTarget("group", GROUP_ID, (MENTION_USER_ID,)),
                MessageTarget("private", PRIVATE_USER_ID),
            ],
            "hello",
            bot=bot,
            interval_seconds=0,
            message_limiter=_limit,
        )
    )

    assert summary.succeeded == [
        MessageTarget("group", GROUP_ID, (MENTION_USER_ID,)),
        MessageTarget("private", PRIVATE_USER_ID),
    ]
    assert summary.failed == []
    assert limiter_calls == [GROUP_ID, None]

    group_id, group_message = bot.group_messages[0]
    assert group_id == GROUP_ID
    assert group_message[0].type == "at"
    assert group_message[0].data["qq"] == str(MENTION_USER_ID)
    assert group_message[-1].data["text"] == f"hello:group={GROUP_ID}"

    user_id, private_message = bot.private_messages[0]
    assert user_id == PRIVATE_USER_ID
    assert private_message[-1].data["text"] == "hello:group=None"


def test_send_target_messages_reports_failed_targets() -> None:
    bot = FakeBot(failed_group_ids={GROUP_ID})

    summary = asyncio.run(
        send_target_messages(
            [
                MessageTarget("group", GROUP_ID),
                MessageTarget("private", PRIVATE_USER_ID),
            ],
            "hello",
            bot=bot,
            interval_seconds=0,
        )
    )

    assert summary.succeeded == [MessageTarget("private", PRIVATE_USER_ID)]
    assert summary.failed == [MessageTarget("group", GROUP_ID)]


def test_send_target_messages_routes_each_target_without_explicit_bot(
    monkeypatch: MonkeyPatch,
) -> None:
    group_bot = FakeBot(self_id=111111111)
    private_bot = FakeBot(self_id=222222222)

    monkeypatch.setattr(
        senders,
        "get_bot_for_target",
        lambda target: group_bot if target.target_type == "group" else private_bot,
    )

    summary = asyncio.run(
        send_target_messages(
            [
                MessageTarget("group", GROUP_ID),
                MessageTarget("private", PRIVATE_USER_ID),
            ],
            "hello",
            interval_seconds=0,
        )
    )

    assert summary.failed == []
    assert group_bot.group_messages[0][0] == GROUP_ID
    assert private_bot.private_messages[0][0] == PRIVATE_USER_ID
    assert not group_bot.private_messages
    assert not private_bot.group_messages


def test_send_target_messages_appends_outbound_cooldown_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    bot = FakeBot()
    decisions = [
        OutboundRateLimitDecision(allowed=True, cooldown_message="进入冷却"),
        OutboundRateLimitDecision(allowed=False),
    ]

    monkeypatch.setattr(
        senders,
        "check_group_outbound_rate_limit",
        lambda _group_id: decisions.pop(0),
    )

    summary = asyncio.run(
        send_target_messages(
            [
                MessageTarget("group", GROUP_ID),
                MessageTarget("group", GROUP_ID + 1),
            ],
            "hello",
            bot=bot,
            interval_seconds=0,
        )
    )

    assert summary.succeeded == [MessageTarget("group", GROUP_ID)]
    assert summary.failed == [MessageTarget("group", GROUP_ID + 1)]
    assert [message[-1].data["text"] for _group_id, message in bot.group_messages] == [
        "hello",
        "进入冷却",
    ]
