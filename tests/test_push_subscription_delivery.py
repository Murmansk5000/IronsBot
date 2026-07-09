from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

from ironsbot.config.models.message import PushUnsubscribeConfig
from ironsbot.shared.messaging import senders
from ironsbot.shared.messaging.outbound_rate_limit import OutboundRateLimitDecision
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore
from ironsbot.shared.messaging.targets import MessageTarget
from tests.helpers.config import stub_app_config


class FakeBot:
    def __init__(self) -> None:
        self.private_messages: list[tuple[int, str]] = []
        self.group_messages: list[tuple[int, str]] = []

    async def send_private_msg(self, *, user_id: int, message: object) -> None:
        self.private_messages.append((user_id, str(message)))

    async def send_group_msg(self, *, group_id: int, message: object) -> None:
        self.group_messages.append((group_id, str(message)))


def test_send_target_messages_filters_unsubscribed_push_targets(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = PushUnsubscribeConfig(
        data_path=str(tmp_path / "push_unsubscriptions.sqlite"),
        hint="回复 TD 管理推送。",
        group_hint="群管理发送 TD 管理推送。",
    )
    store = PushUnsubscribeStore(config.data_path)
    store.unsubscribe_target("private", 1001, "bili_push", "bili_push")
    store.unsubscribe_target("group", 2001, "bili_push", "bili_push")
    bot = FakeBot()

    monkeypatch.setattr(
        senders,
        "get_app_config",
        lambda: stub_app_config(push_unsubscribe_config=config),
    )
    monkeypatch.setattr(
        senders,
        "check_group_outbound_rate_limit",
        lambda _group_id: OutboundRateLimitDecision(allowed=True),
    )

    summary = asyncio.run(
        senders.send_target_messages(
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
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = PushUnsubscribeConfig(
        data_path=str(tmp_path / "push_unsubscriptions.sqlite"),
        hint="回复 TD 管理私聊推送。",
        group_hint="群主/管理员发送 TD 管理本群推送。",
    )
    bot = FakeBot()

    monkeypatch.setattr(
        senders,
        "get_app_config",
        lambda: stub_app_config(push_unsubscribe_config=config),
    )
    monkeypatch.setattr(
        senders,
        "check_group_outbound_rate_limit",
        lambda _group_id: OutboundRateLimitDecision(allowed=True),
    )

    asyncio.run(
        senders.send_target_messages(
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
