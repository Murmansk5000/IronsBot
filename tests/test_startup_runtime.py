import asyncio
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch

from ironsbot.config.models.operations import StartupConfig
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.plugins.onebot import startup_notice as startup_notice_runtime
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeSendSummary,
    AdminNoticeService,
)
from ironsbot.services.operations.startup import StartupNoticeService
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


def _startup_notice_service(
    *parts: tuple[str, str, str],
) -> StartupNoticeService:
    service = StartupNoticeService(build_test_runtime(superuser_ids=(1,)).admin_notices)
    for part in parts:
        service.add(*part)
    return service


def test_startup_notice_appends_db_sync_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object]] = []

    async def fake_send_broadcast_message(
        _service: AdminNoticeService,
        message: object,
        **kwargs: object,
    ) -> AdminNoticeSendSummary:
        assert "bot" not in kwargs
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return AdminNoticeSendSummary((ActorRef(Platform.ONEBOT, "1"),), ())

    monkeypatch.setattr(
        AdminNoticeService,
        "send",
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
        _service: AdminNoticeService,
        message: object,
        **kwargs: object,
    ) -> AdminNoticeSendSummary:
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return AdminNoticeSendSummary((ActorRef(Platform.ONEBOT, "1"),), ())

    monkeypatch.setattr(
        AdminNoticeService,
        "send",
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
