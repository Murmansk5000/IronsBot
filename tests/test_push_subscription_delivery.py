from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.messaging import MessageTarget
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path


class FakeBot:
    def __init__(self) -> None:
        self.private_messages: list[tuple[int, str]] = []
        self.group_messages: list[tuple[int, str]] = []

    async def send_private_msg(self, *, user_id: int, message: object) -> None:
        self.private_messages.append((user_id, str(message)))

    async def send_group_msg(self, *, group_id: int, message: object) -> None:
        self.group_messages.append((group_id, str(message)))


def test_send_target_messages_filters_unsubscribed_push_targets(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "qq_state.sqlite"
    config = PushUnsubscribeConfig(
        hint="回复 TD 管理推送。",
        group_hint="群管理发送 TD 管理推送。",
    )
    store = PushUnsubscribeStore(state_path)
    store.unsubscribe_target("private", 1001, "bili_push", "bili_push")
    store.unsubscribe_target("group", 2001, "bili_push", "bili_push")
    bot = FakeBot()
    delivery = build_test_runtime(
        push_unsubscribe=config,
        state_path=state_path,
    ).delivery

    summary = asyncio.run(
        delivery.send_targets(
            [
                MessageTarget("private", 1001),
                MessageTarget("private", 1002),
                MessageTarget("group", 2001),
                MessageTarget("group", 2002),
            ],
            "推送正文",
            bot=bot,
            subscription_key="bili_push",
        )
    )

    assert [target.target_id for target in summary.succeeded] == [1002, 2002]
    assert bot.private_messages == [(1002, "推送正文\n\n回复 TD 管理推送。")]
    assert bot.group_messages == [(2002, "推送正文\n\n群管理发送 TD 管理推送。")]


def test_send_target_messages_does_not_share_mutated_message_between_targets(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "qq_state.sqlite"
    config = PushUnsubscribeConfig(
        hint="回复 TD 管理私聊推送。",
        group_hint="群主/管理员发送 TD 管理本群推送。",
    )
    bot = FakeBot()
    delivery = build_test_runtime(
        push_unsubscribe=config,
        state_path=state_path,
    ).delivery

    asyncio.run(
        delivery.send_targets(
            [
                MessageTarget("group", 2001),
                MessageTarget("private", 1001),
            ],
            Message("机器人已开启。"),
            bot=bot,
            subscription_key="startup_notice",
        )
    )

    assert bot.group_messages == [
        (2001, "机器人已开启。\n\n群主/管理员发送 TD 管理本群推送。")
    ]
    assert bot.private_messages == [
        (1001, "机器人已开启。\n\n回复 TD 管理私聊推送。")
    ]


def test_send_target_messages_appends_subscription_hint_once_per_day(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "qq_state.sqlite"
    config = PushUnsubscribeConfig(
        hint="回复 TD 管理私聊推送。",
        group_hint="群主/管理员发送 TD 管理本群推送。",
    )
    bot = FakeBot()
    delivery = build_test_runtime(
        push_unsubscribe=config,
        state_path=state_path,
    ).delivery

    asyncio.run(
        delivery.send_targets(
            [MessageTarget("private", 1001), MessageTarget("group", 2001)],
            "第一次",
            bot=bot,
            subscription_key="startup_notice",
        )
    )
    asyncio.run(
        delivery.send_targets(
            [MessageTarget("private", 1001), MessageTarget("group", 2001)],
            "第二次",
            bot=bot,
            subscription_key="startup_notice",
        )
    )
    asyncio.run(
        delivery.send_targets(
            [MessageTarget("group", 2002)],
            "另一个群",
            bot=bot,
            subscription_key="startup_notice",
        )
    )

    assert bot.private_messages == [
        (1001, "第一次\n\n回复 TD 管理私聊推送。"),
        (1001, "第二次"),
    ]
    assert bot.group_messages == [
        (2001, "第一次\n\n群主/管理员发送 TD 管理本群推送。"),
        (2001, "第二次"),
        (2002, "另一个群\n\n群主/管理员发送 TD 管理本群推送。"),
    ]
