import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import Message
from pytest import MonkeyPatch

from ironsbot.config.models.messaging import (
    BotRoutingConfig,
    PushDeliveryConfig,
    PushUnsubscribeConfig,
)
from ironsbot.core.messaging import MessageTarget
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    OutboundPermit,
    OutboundRateLimitDecision,
)
from ironsbot.integrations.onebot.router import BotRouter

GROUP_ID = 10
PRIVATE_USER_ID = 20
MENTION_USER_ID = 30
FANOUT_TARGET_COUNT = 2
PUSH_ATTEMPT_COUNT = 3


class FakeSendError(RuntimeError):
    pass


@dataclass
class FakeOutboundService(GroupOutboundRateLimitService):
    decisions: list[OutboundRateLimitDecision] = field(default_factory=list)
    rollbacks: list[object] = field(default_factory=list)
    _preacquired_push_permit: ContextVar[OutboundPermit | None] = field(
        default_factory=lambda: ContextVar("test_preacquired_permit", default=None),
        init=False,
    )

    async def acquire_push(
        self,
        group_id: int | None,
        *,
        source: str,
    ) -> OutboundRateLimitDecision:
        del group_id, source
        if self.decisions:
            return self.decisions.pop(0)
        return OutboundRateLimitDecision(allowed=True)

    def rollback(self, permit: OutboundPermit | None) -> None:
        self.rollbacks.append(permit)


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


@dataclass
class CoordinatedBot(FakeBot):
    started_group_ids: set[int] = field(default_factory=set)
    both_started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def send_group_msg(self, *, group_id: int, message: Message) -> None:
        self.started_group_ids.add(group_id)
        if len(self.started_group_ids) == FANOUT_TARGET_COUNT:
            self.both_started.set()
        await self.release.wait()
        await super().send_group_msg(group_id=group_id, message=message)


class FakeSubscriptions:
    def filter_subscribed_user_ids(
        self,
        user_ids: list[int],
        subscription_key: str,
    ) -> list[int]:
        del subscription_key
        return user_ids

    def filter_subscribed_group_ids(
        self,
        group_ids: list[int],
        subscription_key: str,
    ) -> list[int]:
        del subscription_key
        return group_ids

    def mark_daily_hint_sent(
        self,
        target_type: str,
        target_id: int,
        hint_key: str,
        *,
        today: str | None = None,
    ) -> bool:
        del target_type, target_id, hint_key, today
        return True

    def target_unsubscribed_keys(
        self,
        target_type: str,
        target_id: int,
    ) -> set[str]:
        del target_type, target_id
        return set()


def _delivery(
    outbound: FakeOutboundService | None = None,
    push_delivery: PushDeliveryConfig | None = None,
    *,
    group_alias_order: tuple[int, ...] = (),
    user_alias_order: tuple[int, ...] = (),
) -> OneBotDelivery:
    return OneBotDelivery(
        outbound or FakeOutboundService(),
        PushUnsubscribeConfig(),
        BotRouter(BotRoutingConfig(), OneBotReferenceResolver({}, {})),
        FakeSubscriptions(),
        push_delivery or PushDeliveryConfig(),
        group_alias_order,
        user_alias_order,
    )


def test_send_target_messages_dedupes_and_limits_by_group() -> None:
    bot = FakeBot()
    limiter_calls: list[MessageTarget] = []

    def _limit(message: str | Message, target: MessageTarget) -> str | Message:
        limiter_calls.append(target)
        return f"{message}:target={target.target_type}:{target.target_id}"

    summary = asyncio.run(
        _delivery().send_targets(
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
    assert limiter_calls == [
        MessageTarget("group", GROUP_ID, (MENTION_USER_ID,)),
        MessageTarget("private", PRIVATE_USER_ID),
    ]

    group_id, group_message = bot.group_messages[0]
    assert group_id == GROUP_ID
    assert group_message[0].type == "at"
    assert group_message[0].data["qq"] == str(MENTION_USER_ID)
    assert group_message[-1].data["text"] == f"hello:target=group:{GROUP_ID}"

    user_id, private_message = bot.private_messages[0]
    assert user_id == PRIVATE_USER_ID
    assert private_message[-1].data["text"] == f"hello:target=private:{PRIVATE_USER_ID}"


def test_send_target_messages_reports_failed_targets() -> None:
    bot = FakeBot(failed_group_ids={GROUP_ID})
    outbound = FakeOutboundService()

    summary = asyncio.run(
        _delivery(outbound).send_targets(
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
    assert outbound.rollbacks == [None]


def test_send_target_messages_routes_each_target_without_explicit_bot(
    monkeypatch: MonkeyPatch,
) -> None:
    group_bot = FakeBot(self_id=111111111)
    private_bot = FakeBot(self_id=222222222)

    monkeypatch.setattr(
        BotRouter,
        "for_target",
        lambda _router, target: (
            group_bot if target.target_type == "group" else private_bot
        ),
    )

    summary = asyncio.run(
        _delivery().send_targets(
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


def test_send_target_messages_reports_push_queue_suppression() -> None:
    bot = FakeBot()
    delivery = _delivery(
        FakeOutboundService(
            decisions=[
                OutboundRateLimitDecision(allowed=True),
                OutboundRateLimitDecision(
                    allowed=False,
                    reason="queue_cleared",
                ),
            ]
        )
    )

    summary = asyncio.run(
        delivery.send_targets(
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
    assert [str(message) for _group_id, message in bot.group_messages] == ["hello"]


def test_subscription_fanout_does_not_stagger_targets() -> None:
    bot = CoordinatedBot()
    delivery = _delivery()

    async def send() -> None:
        task = asyncio.create_task(
            delivery.send_targets(
                [
                    MessageTarget("group", GROUP_ID),
                    MessageTarget("group", GROUP_ID + 1),
                ],
                "hello",
                bot=bot,
                interval_seconds=60.0,
                subscription_key="scheduled_message",
            )
        )
        await asyncio.wait_for(bot.both_started.wait(), timeout=0.1)
        bot.release.set()
        summary = await task
        assert summary.failed == []

    asyncio.run(send())
    assert bot.started_group_ids == {GROUP_ID, GROUP_ID + 1}


def test_push_delivery_retries_with_smaller_batches() -> None:
    class RetryingBot(FakeBot):
        def __init__(self) -> None:
            super().__init__()
            self.attempts: dict[int, int] = {}
            self.active = 0
            self.max_active_by_attempt: dict[int, int] = {}

        async def send_group_msg(self, *, group_id: int, message: Message) -> None:
            attempt = self.attempts.get(group_id, 0) + 1
            self.attempts[group_id] = attempt
            self.active += 1
            self.max_active_by_attempt[attempt] = max(
                self.max_active_by_attempt.get(attempt, 0), self.active
            )
            await asyncio.sleep(0)
            self.active -= 1
            if attempt < PUSH_ATTEMPT_COUNT:
                raise FakeSendError
            await super().send_group_msg(group_id=group_id, message=message)

    bot = RetryingBot()
    delivery = _delivery(
        push_delivery=PushDeliveryConfig(
            max_attempts=3,
            retry_batch_divisor=3,
            batch_delay_min_seconds=0,
            batch_delay_max_seconds=0,
        )
    )
    targets = [MessageTarget("group", GROUP_ID + index) for index in range(9)]

    summary = asyncio.run(
        delivery.send_targets(
            targets,
            "hello",
            bot=bot,
            subscription_key="scheduled_message",
        )
    )

    assert summary.succeeded == targets
    assert summary.failed == []
    assert bot.max_active_by_attempt == {1: 9, 2: 3, 3: 1}


def test_push_delivery_only_retries_failed_targets() -> None:
    class PartialFailureBot(FakeBot):
        def __init__(self) -> None:
            super().__init__()
            self.attempts: dict[int, int] = {}

        async def send_group_msg(self, *, group_id: int, message: Message) -> None:
            attempt = self.attempts.get(group_id, 0) + 1
            self.attempts[group_id] = attempt
            if group_id == GROUP_ID + 1 and attempt == 1:
                raise FakeSendError
            await super().send_group_msg(group_id=group_id, message=message)

    bot = PartialFailureBot()
    delivery = _delivery(
        push_delivery=PushDeliveryConfig(
            batch_delay_min_seconds=0,
            batch_delay_max_seconds=0,
        )
    )
    targets = [MessageTarget("group", GROUP_ID), MessageTarget("group", GROUP_ID + 1)]

    summary = asyncio.run(
        delivery.send_targets(
            targets,
            "hello",
            bot=bot,
            subscription_key="scheduled_message",
        )
    )

    assert summary.succeeded == targets
    assert [group_id for group_id, _message in bot.group_messages] == [
        GROUP_ID,
        GROUP_ID + 1,
    ]


def test_push_delivery_can_leave_failed_targets_for_a_later_round() -> None:
    class AmbiguousFailureBot(FakeBot):
        async def send_group_msg(self, *, group_id: int, message: Message) -> None:
            await super().send_group_msg(group_id=group_id, message=message)
            raise FakeSendError

    bot = AmbiguousFailureBot()
    delivery = _delivery(
        push_delivery=PushDeliveryConfig(
            batch_delay_min_seconds=0,
            batch_delay_max_seconds=0,
        )
    )
    target = MessageTarget("group", GROUP_ID)

    summary = asyncio.run(
        delivery.send_targets(
            [target],
            "image",
            bot=bot,
            subscription_key="scheduled_message",
            retry_failed_targets=False,
        )
    )

    assert summary.succeeded == []
    assert summary.failed == [target]
    assert [group_id for group_id, _message in bot.group_messages] == [GROUP_ID]


def test_push_delivery_orders_targets_by_alias_definition() -> None:
    bot = FakeBot()
    delivery = _delivery(
        group_alias_order=(GROUP_ID + 2, GROUP_ID),
        user_alias_order=(PRIVATE_USER_ID + 2, PRIVATE_USER_ID),
    )
    targets = [
        MessageTarget("private", PRIVATE_USER_ID + 1),
        MessageTarget("group", GROUP_ID + 1),
        MessageTarget("group", GROUP_ID),
        MessageTarget("private", PRIVATE_USER_ID),
        MessageTarget("group", GROUP_ID + 2),
        MessageTarget("private", PRIVATE_USER_ID + 2),
    ]

    summary = asyncio.run(
        delivery.send_targets(
            targets,
            "hello",
            bot=bot,
            subscription_key="scheduled_message",
        )
    )

    assert summary.succeeded == targets
    assert [group_id for group_id, _message in bot.group_messages] == [
        GROUP_ID + 2,
        GROUP_ID,
        GROUP_ID + 1,
    ]
    assert [user_id for user_id, _message in bot.private_messages] == [
        PRIVATE_USER_ID + 2,
        PRIVATE_USER_ID,
        PRIVATE_USER_ID + 1,
    ]


def test_push_batches_share_a_gate_per_bot() -> None:
    class BlockingBot(FakeBot):
        def __init__(self) -> None:
            super().__init__(self_id=1001)
            self.started: list[int] = []
            self.first_started = asyncio.Event()
            self.release = asyncio.Event()

        async def send_group_msg(self, *, group_id: int, message: Message) -> None:
            self.started.append(group_id)
            self.first_started.set()
            await self.release.wait()
            await super().send_group_msg(group_id=group_id, message=message)

    async def _run() -> None:
        bot = BlockingBot()
        delivery = _delivery(
            push_delivery=PushDeliveryConfig(
                max_attempts=1,
                batch_delay_min_seconds=0,
                batch_delay_max_seconds=0,
            )
        )
        first = asyncio.create_task(
            delivery.send_targets(
                [MessageTarget("group", GROUP_ID)],
                "first",
                bot=bot,
                subscription_key="first",
            )
        )
        await asyncio.wait_for(bot.first_started.wait(), timeout=0.1)
        second = asyncio.create_task(
            delivery.send_targets(
                [MessageTarget("group", GROUP_ID + 1)],
                "second",
                bot=bot,
                subscription_key="second",
            )
        )
        await asyncio.sleep(0)
        assert bot.started == [GROUP_ID]
        bot.release.set()
        await asyncio.gather(first, second)

    asyncio.run(_run())


def test_target_messages_fan_out_distinct_payloads() -> None:
    bot = FakeBot()

    summary = asyncio.run(
        _delivery().send_target_messages(
            [
                (MessageTarget("group", GROUP_ID), "first"),
                (MessageTarget("private", PRIVATE_USER_ID), "second"),
            ],
            bot=bot,
            subscription_key="scheduled_message",
        )
    )

    assert summary.succeeded == [
        MessageTarget("group", GROUP_ID),
        MessageTarget("private", PRIVATE_USER_ID),
    ]
    assert str(bot.group_messages[0][1]) == (
        "first\n\n"
        "发送 TD、订阅 或 推送管理 可查看推送订阅；"
        "群主/管理员可切换开关，发送 推送时间 管理提醒时间。"
    )
    assert str(bot.private_messages[0][1]) == "second\n\n回复 TD 可管理推送订阅。"
