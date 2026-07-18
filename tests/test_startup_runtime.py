import asyncio
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch

from ironsbot.config.models.runtime import StartupConfig
from ironsbot.plugins.startup_notice import runtime as startup_notice_runtime
from ironsbot.services.startup_notice import StartupNoticeService
from ironsbot.shared.messaging.admin_notice import AdminNoticeTargets
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


def _startup_notice_service(
    *parts: tuple[str, str, str],
) -> StartupNoticeService:
    service = StartupNoticeService(
        target_loader=lambda: AdminNoticeTargets(
            private_user_ids=[1],
            group_ids=[],
        )
    )
    for part in parts:
        service.add(*part)
    return service


def test_startup_notice_appends_db_sync_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object]] = []
    async def fake_send_broadcast_message(
        message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        assert "bot" not in kwargs
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return TargetSendSummary([MessageTarget("private", 1)], [])

    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    asyncio.run(
        startup_notice_runtime.send_startup_notice(
            cast("Bot", object()),
            _startup_notice_service(
                (
                    "startup_data_sync",
                    "startup data sync notice",
                    "启动数据同步已是最新，无需更新：seerapi, aliases",
                ),
            ),
            StartupConfig(enabled=True, message="机器人已开启。", delay=0),
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
    async def fake_send_broadcast_message(
        message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return TargetSendSummary([MessageTarget("private", 1)], [])

    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    asyncio.run(
        startup_notice_runtime.send_startup_notice(
            cast("Bot", object()),
            _startup_notice_service(
                (
                    "startup_docker_update",
                    "startup docker update notice",
                    "Docker 自更新任务已启动：ironsbot",
                ),
                (
                    "startup_data_sync",
                    "startup data sync notice",
                    "启动数据同步已是最新，无需更新：seerapi",
                ),
            ),
            StartupConfig(enabled=True, message="机器人已开启。", delay=0),
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
