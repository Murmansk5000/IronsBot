import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import nonebot
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.message import PushUnsubscribeConfig
from ironsbot.plugins.messaging import runtime
from ironsbot.shared.messaging.push_subscriptions import PushSubscriptionOption
from ironsbot.shared.promotions import FIRE_MANUAL_LINK_MESSAGE


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


@dataclass(frozen=True, slots=True)
class FakePrivateSchedule:
    message: str
    feature: str = "text_push"
    id: str = "private"


@dataclass(frozen=True, slots=True)
class FakeGroupSchedule:
    message: str
    at_user_ids: list[int]
    feature: str = "text_push"
    id: str = "group"


@dataclass(frozen=True, slots=True)
class FakeMessageConfig:
    push_unsubscribe: PushUnsubscribeConfig


def test_messaging_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        runtime._messaging_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    runtime._setup_messaging_runtime(driver, scheduler)
    runtime._setup_messaging_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1


def test_push_subscription_menu_prompt_marks_current_state() -> None:
    prompt = runtime._push_subscription_menu_prompt(
        "private",
        [
            PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
            PushSubscriptionOption(
                "startup_data_sync",
                "启动数据同步通知",
                "admin_notice",
                unsubscribed=True,
            ),
        ],
    )

    assert "请选择要切换的私聊推送订阅：" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "2. ❌ 启动数据同步通知" in prompt
    assert "输入序号切换" in prompt


def test_scheduled_messages_append_fire_manual_ad(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    async def fake_send_broadcast_message(
        message: str,
        **kwargs: object,
    ) -> None:
        limiter = kwargs.get("message_limiter")
        group_ids = kwargs.get("group_ids")
        if limiter is not None and isinstance(group_ids, list) and group_ids:
            message = limiter(message, group_ids[0])  # type: ignore[operator]
        sent.append((message, kwargs))

    monkeypatch.setattr(runtime, "send_broadcast_message", fake_send_broadcast_message)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(
                data_path=str(tmp_path / "unsubscribe.sqlite")
            )
        ),
    )
    monkeypatch.setattr(runtime, "users_for_feature", lambda _feature: [2001])
    monkeypatch.setattr(runtime, "users_with_superusers", list)
    monkeypatch.setattr(runtime, "groups_for_feature", lambda _feature: [1001])
    monkeypatch.setattr(
        runtime,
        "append_fire_manual_ad_for_group",
        lambda message, _group_id: f"{message}\n\n{FIRE_MANUAL_LINK_MESSAGE}",
    )

    asyncio.run(runtime._send_private_schedule(FakePrivateSchedule(message="私聊定时")))
    asyncio.run(
        runtime._send_group_schedule(
            FakeGroupSchedule(message="群定时", at_user_ids=[3001])
        )
    )

    assert [message for message, _kwargs in sent] == [
        f"私聊定时\n\n{FIRE_MANUAL_LINK_MESSAGE}",
        f"群定时\n\n{FIRE_MANUAL_LINK_MESSAGE}",
    ]
    assert sent[0][1]["private_user_ids"] == [2001]
    assert sent[0][1]["subscription_key"] == "private"
    assert sent[1][1]["group_ids"] == [1001]
    assert sent[1][1]["group_at_user_ids"] == [3001]
    assert sent[1][1]["subscription_key"] == "group"


def test_private_schedule_passes_subscription_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    data_path = tmp_path / "unsubscribe.sqlite"

    async def fake_send_broadcast_message(
        message: str,
        **kwargs: object,
    ) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr(runtime, "send_broadcast_message", fake_send_broadcast_message)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path))
        ),
    )
    monkeypatch.setattr(runtime, "users_for_feature", lambda _feature: [2001, 2002])
    monkeypatch.setattr(runtime, "users_with_superusers", list)

    asyncio.run(runtime._send_private_schedule(FakePrivateSchedule(message="私聊定时")))

    assert sent[0][1]["private_user_ids"] == [2001, 2002]
    assert sent[0][1]["subscription_key"] == "private"
