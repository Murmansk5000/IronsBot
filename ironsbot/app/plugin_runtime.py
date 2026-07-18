# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.app.composition import refresh_push_time_jobs as refresh_jobs

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.config.models.message import (
        SendpicBehaviorConfig,
        TeamAuditWelcomeConfig,
    )
    from ironsbot.config.models.runtime import (
        RestartConfig,
        StartupConfig,
    )
    from ironsbot.plugins.messaging.push_time import PushTimeOption
    from ironsbot.plugins.messaging.runtime_service import MessagingResources
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.bilibili.resources import BilibiliResources
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
    from ironsbot.services.seer.resources import SeerQueryResources
    from ironsbot.services.startup_notice import StartupNoticeService
    from ironsbot.services.team_resource_subscriptions import TeamResourceService
    from ironsbot.shared.features import FeatureService
    from ironsbot.shared.messaging.senders import DeliveryResources


def scheduler() -> Any:
    from nonebot_plugin_apscheduler import scheduler

    return scheduler


def install_seer_query(
    registry: MatcherRegistry,
    resources: SeerQueryResources,
) -> None:
    from ironsbot.plugins.seer.query import install

    install(
        registry,
        resources,
    )


def install_sendpic(
    registry: MatcherRegistry,
    config: SendpicBehaviorConfig,
    cnb_token: str | None,
    features: FeatureService,
) -> None:
    from ironsbot.plugins.sendpic import install

    install(registry, config, cnb_token, features)


async def refresh_push_time_jobs(
    option: PushTimeOption,
    *,
    activity_service: ActivityService,
    messaging: MessagingResources,
) -> None:
    await refresh_jobs(
        option,
        scheduler=scheduler(),
        activity_service=activity_service,
        messaging=messaging,
    )


async def initialize_http_clients() -> None:
    from ironsbot.plugins.http_client.runtime import initialize_http_clients

    await initialize_http_clients()


async def shutdown_http_clients() -> None:
    from ironsbot.plugins.http_client.runtime import shutdown_http_clients

    await shutdown_http_clients()


async def start_messaging(messaging: MessagingResources) -> None:
    from ironsbot.plugins.messaging.runtime import start_messaging as start

    await start(scheduler(), messaging)


async def register_headless_reconnect_jobs(headless: HeadlessService) -> None:
    from ironsbot.config.models.runtime import INVALID_RECONNECT_TIME_ERROR
    from ironsbot.core.time import daily_time_parts
    from ironsbot.integrations.scheduler.jobs import JobRegistry

    registry = JobRegistry(scheduler(), prefix="headless_reconnect_check:")
    for scheduled_time in headless.reconnect_times:
        hour, minute = daily_time_parts(
            scheduled_time,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )
        registry.add(
            headless.reconnect,
            "cron",
            job_id=scheduled_time,
            args=[scheduled_time],
            hour=hour,
            minute=minute,
            second=0,
            timezone="Asia/Shanghai",
        )


async def register_restart_jobs(config: RestartConfig) -> None:
    from ironsbot.plugins.scheduled_restart.runtime import register_restart_jobs

    register_restart_jobs(scheduler(), config)


async def register_bilibili_jobs(
    resources: BilibiliResources,
) -> None:
    from ironsbot.plugins.bilibili.runtime import register_bili_auto_check_job

    await register_bili_auto_check_job(scheduler(), resources)


async def register_activity_jobs(service: ActivityService) -> None:
    service.register_jobs(scheduler())


async def register_team_resource_jobs(
    headless: HeadlessService,
    service: TeamResourceService,
) -> None:
    from ironsbot.plugins.team_resource_subscription.runtime import (
        register_team_resource_jobs,
    )

    register_team_resource_jobs(scheduler(), headless, service)


async def register_local_rank_jobs(
    headless: HeadlessService,
    service: LocalRankService,
) -> None:
    from ironsbot.plugins.seer.query.runtime import register_local_rank_refresh_job

    register_local_rank_refresh_job(scheduler(), headless, service)


async def register_rank_page_jobs(
    headless: HeadlessService,
    service: RankPageRefreshService,
) -> None:
    from ironsbot.plugins.seer.query.runtime import register_rank_page_refresh_jobs

    register_rank_page_refresh_jobs(scheduler(), headless, service)


async def check_headless_seer(_bot: Bot, headless: HeadlessService) -> None:
    await headless.check_on_connect()


async def check_bilibili(
    bot: Bot,
    resources: BilibiliResources,
) -> None:
    from ironsbot.plugins.bilibili.runtime import check_bilibili_on_connect

    await check_bilibili_on_connect(bot, resources)


async def send_startup_notice(
    bot: Bot,
    service: StartupNoticeService,
    config: StartupConfig,
) -> None:
    from ironsbot.plugins.startup_notice.runtime import send_startup_notice

    await send_startup_notice(bot, service, config)


async def team_audit_on_connect(
    bot: Bot,
    config: TeamAuditWelcomeConfig,
    features: FeatureService,
    delivery: DeliveryResources,
) -> None:
    from ironsbot.plugins.team_audit_welcome.followup import (
        register_team_audit_followup_scan,
        schedule_pending_team_audit_followups,
    )

    del bot
    jobs = scheduler()
    await schedule_pending_team_audit_followups(
        jobs,
        config=config,
        features=features,
        delivery=delivery,
    )
    register_team_audit_followup_scan(
        jobs,
        config=config,
        features=features,
        delivery=delivery,
    )
