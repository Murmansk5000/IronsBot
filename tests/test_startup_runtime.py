import asyncio
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch

from ironsbot.config.models.runtime import StartupConfig
from ironsbot.plugins.startup_notice import runtime as startup_notice_runtime
from ironsbot.plugins.startup_notice.service import StartupNoticeProvider
from ironsbot.shared.messaging.admin_notice import AdminNoticeTargets
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


def test_startup_notice_appends_db_sync_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object]] = []
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sent",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sending",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime,
        "get_startup_config",
        lambda: StartupConfig(enabled=True, message="机器人已开启。", delay=0),
    )

    async def fake_send_broadcast_message(
        message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        assert "bot" not in kwargs
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return TargetSendSummary([MessageTarget("private", 1)], [])

    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service,
        "target_loader",
        lambda: AdminNoticeTargets(private_user_ids=[1], group_ids=[]),
    )
    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    asyncio.run(
        startup_notice_runtime.send_startup_notice(
            cast("Bot", object()),
            (
                StartupNoticeProvider(
                    subscription_key="startup_data_sync",
                    action_name="startup data sync notice",
                    get_message=lambda: (
                        "启动数据同步已是最新，无需更新：seerapi, aliases"
                    ),
                ),
            ),
        )
    )

    assert sent_messages == [
        ("机器人已开启。", "startup_notice"),
        (
            "启动数据同步已是最新，无需更新：seerapi, aliases",
            "startup_data_sync",
        ),
    ]


def test_startup_notice_appends_docker_update_before_db_sync(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object]] = []
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sent",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sending",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime,
        "get_startup_config",
        lambda: StartupConfig(enabled=True, message="机器人已开启。", delay=0),
    )

    async def fake_send_broadcast_message(
        message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return TargetSendSummary([MessageTarget("private", 1)], [])

    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service,
        "target_loader",
        lambda: AdminNoticeTargets(private_user_ids=[1], group_ids=[]),
    )
    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    asyncio.run(
        startup_notice_runtime.send_startup_notice(
            cast("Bot", object()),
            (
                StartupNoticeProvider(
                    subscription_key="startup_docker_update",
                    action_name="startup docker update notice",
                    get_message=lambda: "Docker 自更新任务已启动：ironsbot",
                ),
                StartupNoticeProvider(
                    subscription_key="startup_data_sync",
                    action_name="startup data sync notice",
                    get_message=lambda: "启动数据同步已是最新，无需更新：seerapi",
                ),
            ),
        )
    )

    assert sent_messages == [
        ("机器人已开启。", "startup_notice"),
        (
            "Docker 自更新任务已启动：ironsbot",
            "startup_docker_update",
        ),
        ("启动数据同步已是最新，无需更新：seerapi", "startup_data_sync"),
    ]
