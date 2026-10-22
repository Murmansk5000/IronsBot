import asyncio

from pytest import MonkeyPatch

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.operations import StartupConfig
from ironsbot.core.platform import ActorRef, BotAccountRef, Platform
from ironsbot.plugins.onebot import startup_notice as startup_notice_runtime
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeSendSummary,
    AdminNoticeService,
)
from ironsbot.services.operations.startup import StartupNoticeService
from tests.helpers.runtime import build_test_runtime


def _startup_notice_service(
    *parts: tuple[str, str, str],
) -> StartupNoticeService:
    service = StartupNoticeService(
        build_test_runtime(
            superuser_ids=(1,),
            feature_config=FeatureConfig(user_policy={"1": ["admin_notice"]}),
        ).admin_notices
    )
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


def test_official_startup_send_is_not_repeated_on_onebot_connect(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[str] = []

    async def fake_send_broadcast_message(
        _service: AdminNoticeService,
        message: object,
        **_kwargs: object,
    ) -> AdminNoticeSendSummary:
        sent_messages.append(str(message))
        return AdminNoticeSendSummary((ActorRef(Platform.QQ_OFFICIAL, "user"),), ())

    monkeypatch.setattr(
        AdminNoticeService,
        "send",
        fake_send_broadcast_message,
    )
    service = _startup_notice_service()
    config = StartupConfig(enabled=True, message="机器人已开启。", delay=0)

    async def run() -> None:
        contribution = startup_notice_runtime.plugin_contribution(
            service=service, config=config
        )
        lifecycle = ApplicationLifecycle.from_contributions(
            (contribution,),
            task_owner=TaskOwner(),
        )
        lifecycle.first_connection_platforms = frozenset({Platform.QQ_OFFICIAL})
        await lifecycle.startup()
        await lifecycle.bot_connect(BotAccountRef(Platform.ONEBOT, "test-helper"))
        assert not sent_messages
        official = BotAccountRef(Platform.QQ_OFFICIAL, "test-app")
        await lifecycle.bot_connect(official)
        await lifecycle.bot_disconnect(official)
        await lifecycle.bot_connect(official)
        await lifecycle.shutdown()

    asyncio.run(run())

    assert sent_messages == ["机器人已开启。"]
