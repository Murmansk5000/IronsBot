# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import nonebot

from ironsbot.app.composition import refresh_push_time_jobs
from ironsbot.core.features import Feature
from ironsbot.plugins.server_status.command_text import SERVER_STATUS_USAGE
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginDefinition,
    PluginHooks,
)
from ironsbot.services.seer.rank_usage import build_rank_help_message
from ironsbot.services.startup_notice import StartupNoticeService

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.config.models.app import AppConfig
    from ironsbot.config.models.runtime import (
        DockerUpdateConfig,
        RestartConfig,
        ServerStatusConfig,
        StartupConfig,
    )
    from ironsbot.plugins.messaging.push_time import PushTimeOption
    from ironsbot.plugins.messaging.push_time_handlers import RefreshPushTimeJobs
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.runtime.plugins import AsyncHook
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.operations.headless import HeadlessService


class PluginRegistryError(ValueError):
    @classmethod
    def external_load_failed(cls, module: str) -> PluginRegistryError:
        return cls(f"failed to load external plugin: {module}")


def _noop_install(_registry: MatcherRegistry) -> None:
    return


def _external_install(module: str) -> Callable[[MatcherRegistry], None]:
    def install(_registry: MatcherRegistry) -> None:
        if nonebot.load_plugin(module) is None:
            raise PluginRegistryError.external_load_failed(module)

    return install


def _scheduler() -> Any:
    from nonebot_plugin_apscheduler import scheduler

    return scheduler


def _install_admin_priority(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.admin_priority import install

    install(registry)


def _install_server_status(
    registry: MatcherRegistry,
    server_status_config: ServerStatusConfig,
    docker_update_config: DockerUpdateConfig,
    headless: HeadlessService,
) -> None:
    from ironsbot.plugins.server_status.handlers import install

    install(registry, server_status_config, docker_update_config, headless)


def _install_db_sync(
    registry: MatcherRegistry,
    github_token: str,
) -> None:
    from ironsbot.plugins.db_sync import install

    install(registry, github_token)


def _install_seer_data(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.seer_data import install

    install(registry)


def _install_messaging(
    registry: MatcherRegistry,
    refresh_jobs: RefreshPushTimeJobs,
) -> None:
    from ironsbot.plugins.messaging import install
    from ironsbot.shared.messaging.outbound_rate_limit import (
        install_outbound_rate_limit_hooks,
    )

    install_outbound_rate_limit_hooks()
    install(registry, refresh_jobs)


def _install_bilibili(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.bilibili.commands import install

    install(registry)


def _install_activity(
    registry: MatcherRegistry,
    service: ActivityService,
) -> None:
    from ironsbot.plugins.activity import install

    install(registry, service)


def _install_team_resource(
    registry: MatcherRegistry,
    headless: HeadlessService,
) -> None:
    from ironsbot.plugins.team_resource_subscription import install

    install(registry, headless)


def _install_seer_query(
    registry: MatcherRegistry,
    headless: HeadlessService,
) -> None:
    from ironsbot.plugins.seer.query import install

    install(registry, headless)


def _install_team_audit(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.team_audit_welcome import install

    install(registry)


def _install_red_packet_notice(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.red_packet_notice import install

    install(registry)


def _install_ai_chat(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.ai_chat import install

    install(registry)


def _install_ai_mention_guard(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.ai_mention_guard import install

    install(registry)


def _install_ai_intent(
    registry: MatcherRegistry,
    headless: HeadlessService,
) -> None:
    from ironsbot.plugins.ai_intent import install

    install(registry, headless)


def _install_about(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.about import install

    install(registry)


def _install_help_hint(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.help_hint import install

    install(registry)


def _install_sendpic(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.sendpic import install

    install(registry)


def _install_meeting(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.meeting import install

    install(registry)


def _install_rank_help(registry: MatcherRegistry) -> None:
    from ironsbot.plugins.seer.rank_help import install

    install(registry)


async def _refresh_push_time_jobs(
    option: PushTimeOption,
    *,
    activity_service: ActivityService,
) -> None:
    await refresh_push_time_jobs(
        option,
        scheduler=_scheduler(),
        activity_service=activity_service,
    )


async def _initialize_http_clients() -> None:
    from ironsbot.plugins.http_client.runtime import initialize_http_clients

    await initialize_http_clients()


async def _shutdown_http_clients() -> None:
    from ironsbot.plugins.http_client.runtime import shutdown_http_clients

    await shutdown_http_clients()


async def _start_messaging() -> None:
    from ironsbot.plugins.messaging.runtime import start_messaging

    await start_messaging(_scheduler())


async def _register_headless_reconnect_jobs(
    headless: HeadlessService,
) -> None:
    from ironsbot.config.models.runtime import INVALID_RECONNECT_TIME_ERROR
    from ironsbot.core.time import daily_time_parts
    from ironsbot.integrations.scheduler.jobs import JobRegistry

    registry = JobRegistry(_scheduler(), prefix="headless_reconnect_check:")
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


async def _register_restart_jobs(config: RestartConfig) -> None:
    from ironsbot.plugins.scheduled_restart.runtime import register_restart_jobs

    register_restart_jobs(_scheduler(), config)


async def _register_bilibili_jobs() -> None:
    from ironsbot.plugins.bilibili.runtime import register_bili_auto_check_job

    await register_bili_auto_check_job(_scheduler())


async def _register_activity_jobs(service: ActivityService) -> None:
    service.register_jobs(_scheduler())


async def _register_team_resource_jobs(
    headless: HeadlessService,
) -> None:
    from ironsbot.plugins.team_resource_subscription.runtime import (
        register_team_resource_jobs,
    )

    register_team_resource_jobs(_scheduler(), headless)


async def _register_local_rank_jobs(headless: HeadlessService) -> None:
    from ironsbot.plugins.seer.query.runtime import register_local_rank_refresh_job

    register_local_rank_refresh_job(_scheduler(), headless)


async def _register_rank_page_jobs(headless: HeadlessService) -> None:
    from ironsbot.plugins.seer.query.runtime import register_rank_page_refresh_jobs

    register_rank_page_refresh_jobs(_scheduler(), headless)


async def _check_headless_seer(
    _bot: Bot,
    headless: HeadlessService,
) -> None:
    await headless.check_on_connect()


async def _check_bilibili(bot: Bot) -> None:
    from ironsbot.plugins.bilibili.runtime import check_bilibili_on_connect

    await check_bilibili_on_connect(bot)


async def _send_startup_notice(
    bot: Bot,
    service: StartupNoticeService,
    config: StartupConfig,
) -> None:
    from ironsbot.plugins.startup_notice.runtime import send_startup_notice

    await send_startup_notice(bot, service, config)


async def _report_render_crash(_bot: Bot) -> None:
    from ironsbot.services.seer.render_crash_report import (
        report_previous_render_crash,
    )

    await report_previous_render_crash()


async def _team_audit_on_connect(bot: Bot) -> None:
    from ironsbot.plugins.team_audit_welcome.runtime import (
        schedule_team_audit_followups_on_connect,
    )

    await schedule_team_audit_followups_on_connect(
        bot,
        scheduler=_scheduler(),
    )


def build_plugin_registry(
    *,
    config: AppConfig,
    activity_service: ActivityService,
    headless: HeadlessService,
    github_token: str,
    shutdown_activity: AsyncHook,
) -> tuple[PluginDefinition, ...]:
    definitions: tuple[PluginDefinition, ...] = ()
    runtime_config = config.runtime
    push_time_refresher = partial(
        _refresh_push_time_jobs,
        activity_service=activity_service,
    )
    startup_notice_service = StartupNoticeService()

    async def start_docker_update() -> None:
        from ironsbot.plugins.server_status.runtime import (
            start_docker_update as run_update,
        )

        startup_notice_service.add(
            "startup_docker_update",
            "startup docker update notice",
            await run_update(runtime_config.docker_update),
        )

    async def start_data_sync() -> None:
        from ironsbot.plugins.db_sync.runtime import start_db_sync

        startup_notice_service.add(
            "startup_data_sync",
            "startup data sync notice",
            await start_db_sync(
                _scheduler(),
                runtime_config.data_sync,
                github_token,
            ),
        )

    def install_help(registry: MatcherRegistry) -> None:
        from ironsbot.plugins import help as help_plugin

        help_plugin.install(registry, definitions)

    definitions = (
        PluginDefinition(
            id="apscheduler",
            features=frozenset(),
            help=None,
            install=_external_install("nonebot_plugin_apscheduler"),
        ),
        PluginDefinition(
            id="localstore",
            features=frozenset(),
            help=None,
            install=_external_install("nonebot_plugin_localstore"),
        ),
        PluginDefinition(
            id="htmlkit",
            features=frozenset(),
            help=None,
            install=_external_install("nonebot_plugin_htmlkit"),
        ),
        PluginDefinition(
            id="saa",
            features=frozenset(),
            help=None,
            install=_external_install("nonebot_plugin_saa"),
        ),
        PluginDefinition(
            id="admin_priority",
            features=frozenset(),
            help=None,
            install=_install_admin_priority,
        ),
        PluginDefinition(
            id="http_client",
            features=frozenset(),
            help=None,
            install=_noop_install,
            hooks=PluginHooks(
                startup=(("http_client", _initialize_http_clients),),
                shutdown=(("http_client", _shutdown_http_clients),),
            ),
        ),
        PluginDefinition(
            id="server_status",
            features=frozenset(
                {Feature.SERVER_STATUS_QUERY, Feature.SERVER_STATUS_PUSH}
            ),
            help=HelpEntry(
                name="开服查询",
                description=(
                    "查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服"
                ),
                usage=SERVER_STATUS_USAGE,
                group="seer",
                order=70,
            ),
            install=partial(
                _install_server_status,
                server_status_config=runtime_config.server_status,
                docker_update_config=runtime_config.docker_update,
                headless=headless,
            ),
            hooks=PluginHooks(
                startup=(("docker_update", start_docker_update),),
            ),
        ),
        PluginDefinition(
            id="db_sync",
            features=frozenset(),
            help=None,
            install=partial(
                _install_db_sync,
                github_token=github_token,
            ),
            hooks=PluginHooks(
                startup=(("db_sync", start_data_sync),),
            ),
        ),
        PluginDefinition(
            id="seer_data",
            features=frozenset(),
            help=None,
            install=_install_seer_data,
        ),
        PluginDefinition(
            id="headless_seer",
            features=frozenset(),
            help=None,
            install=_noop_install,
            hooks=PluginHooks(
                startup=(("headless_seer", headless.start),),
                shutdown=(("headless_seer", headless.shutdown),),
            ),
        ),
        PluginDefinition(
            id="messaging",
            features=frozenset(
                {
                    Feature.TEXT,
                    Feature.TEXT_PUSH,
                    Feature.WEB_ACTIVITY_LINK,
                    Feature.WEB_ACTIVITY_PUSH,
                    Feature.SEERINFO,
                }
            ),
            help=HelpEntry(
                name="文本发送",
                description="按配置回复固定文本/链接，也可定时向群或私聊发送文本",
                usage=(
                    "【文本发送】\n"
                    "按 message 配置组中的关键词回复固定文本。\n"
                    "按 message 配置组中的定时任务推送文本。\n"
                    "常用场景：签到链接、活动链接、信息聚合页、群公告等。"
                ),
                group="message",
                order=30,
            ),
            install=partial(
                _install_messaging,
                refresh_jobs=push_time_refresher,
            ),
            hooks=PluginHooks(
                startup=(("messaging", _start_messaging),),
            ),
        ),
        PluginDefinition(
            id="headless_notice",
            features=frozenset(),
            help=HelpEntry(
                name="自定义无头登录",
                description="自定义无头登录状态检查、掉线播报和定时重连",
                usage=(
                    "【自定义无头登录】\n"
                    "启动后检查无头米米号是否登录成功。\n"
                    "登录状态变化只通知 admin_notice 管理目标。"
                ),
                group="admin",
                order=40,
            ),
            install=_noop_install,
            hooks=PluginHooks(
                startup=(
                    (
                        "headless_reconnect_jobs",
                        partial(_register_headless_reconnect_jobs, headless),
                    ),
                ),
                first_bot_connect=(
                    (
                        "headless_seer_check",
                        partial(_check_headless_seer, headless=headless),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="scheduled_restart",
            features=frozenset(),
            help=None,
            install=_noop_install,
            hooks=PluginHooks(
                startup=(
                    (
                        "scheduled_restart_jobs",
                        partial(_register_restart_jobs, runtime_config.restart),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="bilibili",
            features=frozenset({Feature.BILI_QUERY, Feature.BILI_PUSH}),
            help=HelpEntry(
                name="B站动态",
                description="查询、刷新和自动推送配置账号的 Bilibili 动态",
                usage=(
                    "【B站动态】\n"
                    "动态：查看订阅账号的最新动态。\n"
                    "/动态更新、/动态刷新：超级管理员手动刷新。\n"
                    "B站账号：查看当前会话订阅账号。\n"
                    "B站推送模式 <账号昵称> <内容|链接|默认>：修改群推送模式。"
                ),
                group="message",
                order=20,
            ),
            install=_install_bilibili,
            hooks=PluginHooks(
                startup=(("bilibili_monitor_jobs", _register_bilibili_jobs),),
                first_bot_connect=(("bilibili_check", _check_bilibili),),
            ),
        ),
        PluginDefinition(
            id="activity",
            features=frozenset(
                {Feature.SEER_ACTIVITY_QUERY, Feature.SEER_ACTIVITY_PUSH}
            ),
            help=HelpEntry(
                name="活动结束提醒",
                description="读取活动结束时间并提前提醒即将结束的活动",
                usage=(
                    "【活动结束提醒】\n"
                    "按 activity.lead_hours 配置提前提醒。\n"
                    "发送 当前活动 或 快结束活动 查询活动。"
                ),
                group="message",
                order=10,
            ),
            install=partial(_install_activity, service=activity_service),
            hooks=PluginHooks(
                startup=(
                    (
                        "activity_reminder_jobs",
                        partial(_register_activity_jobs, activity_service),
                    ),
                ),
                shutdown=(("activity", shutdown_activity),),
            ),
        ),
        PluginDefinition(
            id="team_resource",
            features=frozenset({Feature.TEAM_RESOURCE_SUBSCRIPTION}),
            help=HelpEntry(
                name="战队资源订阅",
                description="群内订阅战队，并在资源不足时定时提醒指定用户。",
                usage=(
                    "【战队资源订阅】\n"
                    "发送 战队 查询本群订阅。\n"
                    "群主/管理员可发送：订阅战队123456、"
                    "取消订阅战队123456、战队订阅。"
                ),
                group="seer",
                order=50,
            ),
            install=partial(_install_team_resource, headless=headless),
            hooks=PluginHooks(
                startup=(
                    (
                        "team_resource_jobs",
                        partial(_register_team_resource_jobs, headless),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="startup_notice",
            features=frozenset(),
            help=None,
            install=_noop_install,
            hooks=PluginHooks(
                first_bot_connect=(
                    (
                        "startup_notice",
                        partial(
                            _send_startup_notice,
                            service=startup_notice_service,
                            config=runtime_config.startup_notice,
                        ),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="seer_query",
            features=frozenset(
                {
                    Feature.SEER,
                    Feature.SEER_PLAYER,
                    Feature.SEER_TEAM,
                    Feature.SEER_PET,
                    Feature.SEER_MINTMARK,
                    Feature.SEER_EQUIPMENT,
                    Feature.SEER_TYPE,
                    Feature.SEER_PEAK,
                    Feature.SEER_AUTOCARD,
                    Feature.SEER_RANK,
                    Feature.SEER_DATA,
                }
            ),
            help=HelpEntry(
                name="赛尔号查询",
                description="按当前权限开放赛尔号查询子功能",
                usage="帮助菜单会按当前会话权限显示可用的赛尔号查询指令。",
                group="seer",
                order=10,
            ),
            install=partial(_install_seer_query, headless=headless),
            hooks=PluginHooks(
                startup=(
                    ("local_rank_jobs", partial(_register_local_rank_jobs, headless)),
                    ("rank_page_jobs", partial(_register_rank_page_jobs, headless)),
                ),
                first_bot_connect=(("render_crash_report", _report_render_crash),),
            ),
        ),
        PluginDefinition(
            id="team_audit",
            features=frozenset({Feature.TEAM_AUDIT}),
            help=None,
            install=_install_team_audit,
            hooks=PluginHooks(
                bot_connect=(("team_audit_followups", _team_audit_on_connect),),
            ),
        ),
        PluginDefinition(
            id="fire_manual_ad",
            features=frozenset({Feature.FIRE_MANUAL_AD}),
            help=None,
            install=_noop_install,
        ),
        PluginDefinition(
            id="red_packet_notice",
            features=frozenset(),
            help=None,
            install=_install_red_packet_notice,
        ),
        PluginDefinition(
            id="ai_chat",
            features=frozenset({Feature.AI_CHAT, Feature.ADMIN_NOTICE}),
            help=HelpEntry(
                name="AI聊天",
                description="接入 OpenAI-compatible API 的自定义聊天插件",
                usage="群聊中 @机器人 并附带问题；私聊中直接发送问题。",
                group="ai",
                order=10,
            ),
            install=_install_ai_chat,
        ),
        PluginDefinition(
            id="ai_mention_guard",
            features=frozenset({Feature.AI_CHAT}),
            help=None,
            install=_install_ai_mention_guard,
        ),
        PluginDefinition(
            id="ai_intent",
            features=frozenset(
                {
                    Feature.AI_INTENT,
                    Feature.AI_INTENT_TEAM_RECOMMEND,
                    Feature.AI_INTENT_FIRE_MANUAL,
                }
            ),
            help=HelpEntry(
                name="AI意图分析",
                description="按配置识别简短意图，并触发对应回复或功能。",
                usage=(
                    "【AI意图分析】\n"
                    "按 ai.intent_actions 配置进行关键词粗筛和意图判断。"
                ),
                group="ai",
                order=20,
            ),
            install=partial(_install_ai_intent, headless=headless),
        ),
        PluginDefinition(
            id="about",
            features=frozenset({Feature.ABOUT}),
            help=HelpEntry(
                name="关于",
                description="IronsBot 项目信息与当前版本",
                usage="发送“关于”查看 IronsBot 当前版本、项目地址和主要能力。",
                group="core",
                order=20,
                visibility="always",
            ),
            install=_install_about,
        ),
        PluginDefinition(
            id="help",
            features=frozenset({Feature.HELP}),
            help=HelpEntry(
                name="帮助",
                description="按当前群/私聊权限显示可用功能",
                usage="发送“帮助”查看当前会话可用功能。",
                group="core",
                order=10,
                visibility="always",
            ),
            install=install_help,
        ),
        PluginDefinition(
            id="help_hint",
            features=frozenset(),
            help=None,
            install=_install_help_hint,
        ),
        PluginDefinition(
            id="sendpic",
            features=frozenset({Feature.IMAGE}),
            help=None,
            install=_install_sendpic,
        ),
        PluginDefinition(
            id="meeting",
            features=frozenset({Feature.MEETING}),
            help=HelpEntry(
                name="会议回复",
                description="按配置回复腾讯会议信息",
                usage="发送配置的会议口令获取腾讯会议信息。",
                group="message",
                order=40,
            ),
            install=_install_meeting,
        ),
        PluginDefinition(
            id="rank_help",
            features=frozenset({Feature.SEER_RANK}),
            help=HelpEntry(
                name="榜单",
                description="查看全服榜、机器人样本榜、巅峰样本榜和刻印数值榜",
                usage=build_rank_help_message(),
                group="seer",
                order=20,
            ),
            install=_install_rank_help,
        ),
    )
    validate_plugin_registry(definitions)
    return definitions


def validate_plugin_registry(
    definitions: tuple[PluginDefinition, ...],
) -> None:
    ids = [definition.id for definition in definitions]
    duplicates = sorted({plugin_id for plugin_id in ids if ids.count(plugin_id) > 1})
    if duplicates:
        raise PluginRegistryError("duplicate plugin ids: " + ", ".join(duplicates))

    owned_features = {
        feature for definition in definitions for feature in definition.features
    }
    missing = sorted(
        set(Feature) - owned_features,
        key=lambda feature: feature.value,
    )
    if missing:
        raise PluginRegistryError(
            "features have no owning plugin: "
            + ", ".join(feature.value for feature in missing)
        )


__all__ = [
    "PluginRegistryError",
    "build_plugin_registry",
    "validate_plugin_registry",
]
