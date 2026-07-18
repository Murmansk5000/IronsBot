# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.app.lifecycle import (
    ApplicationLifecycle,
    AsyncHook,
    NamedAsyncHook,
    NamedBotHook,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from nonebot.internal.driver import Driver


def _sync_startup_hook(
    name: str,
    callback: Callable[[], None],
) -> NamedAsyncHook:
    async def run() -> None:
        callback()

    return name, run


def _bot_hook_without_argument(
    name: str,
    callback: AsyncHook,
) -> NamedBotHook:
    async def run(_bot: object) -> None:
        await callback()

    return name, run


def build_application_lifecycle(
    driver: Driver,
    scheduler: AsyncIOScheduler,
) -> ApplicationLifecycle:
    from ironsbot.app.command_cooldown_manifest import (
        install_command_cooldown_policy,
    )
    from ironsbot.plugins.activity import runtime as activity_runtime
    from ironsbot.plugins.bilibili import runtime as bilibili_runtime
    from ironsbot.plugins.db_sync import runtime as db_sync_runtime
    from ironsbot.plugins.headless_seer import runtime as headless_seer_runtime
    from ironsbot.plugins.headless_seer_notice import (
        runtime as headless_notice_runtime,
    )
    from ironsbot.plugins.http_client import runtime as http_client_runtime
    from ironsbot.plugins.messaging import runtime as messaging_runtime
    from ironsbot.plugins.scheduled_restart import runtime as restart_runtime
    from ironsbot.plugins.seer.query import runtime as seer_runtime
    from ironsbot.plugins.server_status import runtime as docker_update_runtime
    from ironsbot.plugins.startup_notice.runtime import send_startup_notice
    from ironsbot.plugins.team_audit_welcome.runtime import (
        schedule_team_audit_followups_on_connect,
    )
    from ironsbot.plugins.team_resource_subscription import (
        runtime as team_resource_runtime,
    )
    from ironsbot.services.activity.runtime_keys import (
        ACTIVITY_REMINDER_REFRESH_KEY,
    )
    from ironsbot.services.seer.render_crash_report import (
        report_previous_render_crash,
    )
    from ironsbot.shared.messaging.outbound_rate_limit import (
        install_outbound_rate_limit_hooks,
    )
    from ironsbot.shared.runtime.refresh import register_runtime_refresh
    from ironsbot.shared.runtime.startup_notice import (
        register_startup_notice_provider,
    )

    def install_startup_notice_providers() -> None:
        register_startup_notice_provider(
            "docker_update",
            subscription_key="startup_docker_update",
            action_name="startup docker update notice",
            get_message=docker_update_runtime.get_startup_docker_update_notice,
        )
        register_startup_notice_provider(
            "db_sync",
            subscription_key="startup_data_sync",
            action_name="startup data sync notice",
            get_message=db_sync_runtime.get_startup_sync_notice,
        )

    def install_runtime_refreshes() -> None:
        register_runtime_refresh(
            messaging_runtime.MESSAGE_SCHEDULE_REFRESH_KEY,
            partial(messaging_runtime.register_message_schedules, scheduler),
        )
        register_runtime_refresh(
            ACTIVITY_REMINDER_REFRESH_KEY,
            partial(activity_runtime.schedule_activity_reminders, scheduler),
        )

    startup_hooks: tuple[NamedAsyncHook, ...] = (
        ("http_client", http_client_runtime.initialize_http_clients),
        ("docker_update", docker_update_runtime.start_docker_update),
        ("db_sync", partial(db_sync_runtime.start_db_sync, scheduler)),
        ("headless_seer", headless_seer_runtime.login_headless_seer),
        ("messaging", partial(messaging_runtime.start_messaging, scheduler)),
        _sync_startup_hook(
            "headless_reconnect_jobs",
            partial(headless_notice_runtime.register_reconnect_checks, scheduler),
        ),
        _sync_startup_hook(
            "scheduled_restart_jobs",
            partial(restart_runtime.register_restart_jobs, scheduler),
        ),
        (
            "bilibili_monitor_jobs",
            partial(bilibili_runtime.register_bili_auto_check_job, scheduler),
        ),
        _sync_startup_hook(
            "activity_reminder_jobs",
            partial(activity_runtime.register_activity_reminder_jobs, scheduler),
        ),
        _sync_startup_hook(
            "team_resource_jobs",
            partial(team_resource_runtime.register_team_resource_jobs, scheduler),
        ),
        _sync_startup_hook(
            "local_rank_jobs",
            partial(seer_runtime.register_local_rank_refresh_job, scheduler),
        ),
        _sync_startup_hook(
            "rank_page_jobs",
            partial(seer_runtime.register_rank_page_refresh_jobs, scheduler),
        ),
    )
    shutdown_hooks: tuple[NamedAsyncHook, ...] = (
        ("http_client", http_client_runtime.shutdown_http_clients),
        ("headless_seer", headless_seer_runtime.shutdown_headless_seer),
    )
    first_bot_connect_hooks = (
        ("headless_seer_check", headless_notice_runtime.check_headless_on_connect),
        ("bilibili_check", bilibili_runtime.check_bilibili_on_connect),
        ("startup_notice", send_startup_notice),
        _bot_hook_without_argument(
            "render_crash_report",
            report_previous_render_crash,
        ),
    )
    bot_connect_hooks = (
        (
            "team_audit_followups",
            partial(
                schedule_team_audit_followups_on_connect,
                scheduler=scheduler,
            ),
        ),
    )

    return ApplicationLifecycle(
        driver=driver,
        installers=(
            ("command_cooldown", install_command_cooldown_policy),
            ("outbound_rate_limit", install_outbound_rate_limit_hooks),
            ("startup_notice_providers", install_startup_notice_providers),
            ("runtime_refreshes", install_runtime_refreshes),
        ),
        startup_hooks=startup_hooks,
        shutdown_hooks=shutdown_hooks,
        first_bot_connect_hooks=first_bot_connect_hooks,
        bot_connect_hooks=bot_connect_hooks,
    )


__all__ = ["build_application_lifecycle"]
