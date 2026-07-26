# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.core.features import Feature
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.plugins.operations.status.command_text import SERVER_STATUS_USAGE
from ironsbot.runtime.feature_policy import event_has_feature
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginDefinition,
    PluginHooks,
    PluginInstall,
)
from ironsbot.runtime.replies import (
    append_fire_manual_ad_message,
    append_text_hint,
)
from ironsbot.services.bilibili.delivery import BilibiliPushDeliveryService
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from ironsbot.services.operations.docker_preflight import (
    consume_docker_startup_preflight_notice,
)
from ironsbot.services.seer.rank_usage import build_rank_help_message

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.app.composition import ApplicationResources
    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.features import FeatureService
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.runtime.matchers import MatcherRegistry


class PluginRegistryError(ValueError):
    @classmethod
    def external_load_failed(cls, module: str) -> PluginRegistryError:
        return cls(f"failed to load external plugin: {module}")


def _load_external_plugin(module: str) -> None:
    if nonebot.load_plugin(module) is None:
        raise PluginRegistryError.external_load_failed(module)


def _external_install(module: str) -> PluginInstall:
    def install(_registry: MatcherRegistry) -> None:
        _load_external_plugin(module)

    return install


def _always_help_visible(_event: Event) -> bool:
    return True


def _feature_help_visible(
    event: Event,
    *,
    features: FeatureService,
    feature: str,
    enabled: bool = True,
    group_only: bool = False,
) -> bool:
    return (
        enabled
        and (not group_only or isinstance(event, GroupMessageEvent))
        and event_has_feature(features, event, feature)
    )


def _superuser_help_visible(
    event: Event,
    *,
    features: FeatureService,
) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and features.is_superuser(int(user_id))


def _messaging_help_visible(
    event: Event,
    *,
    features: FeatureService,
    config: MessageConfig,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        actions = [*config.group_commands, *config.group_schedules]
    elif isinstance(event, PrivateMessageEvent):
        actions = [*config.private_commands, *config.private_schedules]
    else:
        return False
    return any(
        action.enabled
        and event_has_feature(features, event, action.feature)
        for action in actions
    )


def build_plugin_registry(  # noqa: PLR0915 - declarative registry
    *,
    settings: Settings,
    resources: ApplicationResources,
    scheduler: SchedulerFacade,
) -> tuple[PluginDefinition, ...]:
    from ironsbot.custom_plugins.pet_config import (
        plugin_definition as pet_config_definition,
    )
    from ironsbot.plugins.about import install as install_about
    from ironsbot.plugins.activity import install as install_activity
    from ironsbot.plugins.ai import install as install_ai
    from ironsbot.plugins.ai.intent import install as install_ai_intent
    from ironsbot.plugins.bilibili.auth import send_bili_login_notice
    from ironsbot.plugins.bilibili.commands import install as install_bilibili
    from ironsbot.plugins.bilibili.delivery import build_dynamic_message
    from ironsbot.plugins.help.hint import install as install_help_hint
    from ironsbot.plugins.messaging.matchers import install as install_messaging
    from ironsbot.plugins.messaging.meeting import install as install_meeting
    from ironsbot.plugins.messaging.priority import install as install_admin_priority
    from ironsbot.plugins.messaging.red_packet import (
        install as install_red_packet_notice,
    )
    from ironsbot.plugins.operations.db_sync import install as install_db_sync
    from ironsbot.plugins.operations.headless import register_reconnect_jobs
    from ironsbot.plugins.operations.restart import register_restart_jobs
    from ironsbot.plugins.operations.startup import send_startup_notice
    from ironsbot.plugins.operations.status.handlers import (
        install as install_server_status,
    )
    from ironsbot.plugins.seer.rank_help import install as install_rank_help
    from ironsbot.plugins.seer.runtime import (
        register_local_rank_refresh_job,
        register_rank_page_refresh_jobs,
    )
    from ironsbot.plugins.team import install as install_team_audit
    from ironsbot.plugins.team.resource import (
        install as install_team_resource,
    )
    config = settings
    features = resources.features
    delivery = resources.delivery
    admin_notices = resources.admin_notices
    activity_service = resources.activity
    headless = resources.headless
    server_status = resources.server_status
    priority_service = resources.priority
    bilibili_service = resources.bilibili
    bilibili_login = resources.bilibili_login
    messaging = resources.messaging
    sendpic_service = resources.sendpic
    team_audit_service = resources.team_audit
    team_resource_service = resources.team_resource
    local_rank_service = resources.local_rank
    rank_page_refresh_service = resources.rank_page_refresh
    seer_resources = resources.seer
    pet_config_service = resources.pet_config
    ai_service = resources.ai
    data_sync_service = resources.data_sync
    docker_update_service = resources.docker_update
    startup_notice_service = resources.startup_notice
    help_hint_service = resources.help_hint
    bili_notice_sender = partial(send_bili_login_notice, admin_notices)
    bili_auth_invalid = partial(
        bilibili_login.notify_required,
        send_notice=bili_notice_sender,
        is_online=lambda: delivery.default_bot() is not None,
    )
    bili_push_delivery = BilibiliPushDeliveryService(
        features,
        delivery,
        resources.subscriptions,
        build_dynamic_message,
        append_fire_manual_ad_message,
        append_text_hint,
    )
    bili_monitor = BilibiliMonitorService(
        bilibili_service,
        bili_auth_invalid,
        bili_push_delivery.send,
    )
    definitions: tuple[PluginDefinition, ...] = ()

    def install_scheduler(_registry: MatcherRegistry) -> None:
        _load_external_plugin("nonebot_plugin_apscheduler")
        from nonebot_plugin_apscheduler import scheduler as backend

        scheduler.bind(backend)

    async def report_render_crash(_bot: Bot) -> None:
        from ironsbot.services.seer.render_crash_report import (
            report_previous_render_crash,
        )

        await report_previous_render_crash(
            admin_notices,
            config.bot.logging,
            config.paths.log_file,
        )

    push_time_refresher = partial(
        messaging.refresh_push_time_jobs,
        scheduler=scheduler,
        activity_service=activity_service,
    )

    async def check_headless_on_connect(_bot: Bot) -> None:
        await headless.check_on_connect()

    async def check_bilibili_on_connect(bot: Bot) -> None:
        await bili_monitor.check_on_connect(str(bot.self_id))

    def install_seer_query(registry: MatcherRegistry) -> None:
        from ironsbot.plugins.seer.query.commands.install import install
        from ironsbot.plugins.seer.query.group import SeerMatcherGroup

        install(
            SeerMatcherGroup(
                registry,
                seer_resources,
                features,
                priority_service.release,
            )
        )

    def install_sendpic(registry: MatcherRegistry) -> None:
        from ironsbot.plugins.sendpic.matchers import (
            install as install_configured_images,
        )

        install_configured_images(
            registry,
            sendpic_service,
            features,
        )

    def start_docker_update() -> None:
        startup_notice_service.add(
            "startup_docker_update",
            "startup docker update notice",
            consume_docker_startup_preflight_notice(),
        )

    async def start_data_sync() -> None:
        startup_notice_service.add(
            "startup_data_sync",
            "startup data sync notice",
            await data_sync_service.startup(scheduler),
        )

    def install_help(registry: MatcherRegistry) -> None:
        from ironsbot.plugins import help as help_plugin

        help_plugin.install(
            registry,
            definitions,
            features,
            ignored_plugins=tuple(config.features.help.ignored_plugins),
        )

    definitions = (
        PluginDefinition(
            id="apscheduler",
            install=install_scheduler,
            hooks=PluginHooks(
                startup=(("scheduler", scheduler.start),),
                shutdown=(("scheduler", scheduler.shutdown),),
            ),
        ),
        PluginDefinition(
            id="localstore",
            install=_external_install("nonebot_plugin_localstore"),
        ),
        PluginDefinition(
            id="htmlkit",
            install=_external_install("nonebot_plugin_htmlkit"),
        ),
        PluginDefinition(
            id="saa",
            install=_external_install("nonebot_plugin_saa"),
        ),
        PluginDefinition(
            id="admin_priority",
            install=partial(
                install_admin_priority,
                service=priority_service,
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
                install_server_status,
                server_status_config=config.operations.server_status,
                docker_service=docker_update_service,
                server_status=server_status,
                features=features,
                delivery=delivery,
            ),
            hooks=PluginHooks(
                startup=(("docker_update", start_docker_update),),
            ),
        ),
        PluginDefinition(
            id="db_sync",
            install=partial(
                install_db_sync,
                service=data_sync_service,
            ),
            hooks=PluginHooks(
                startup=(("db_sync", start_data_sync),),
            ),
        ),
        PluginDefinition(
            id="headless_seer",
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
                visible=partial(
                    _messaging_help_visible,
                    features=features,
                    config=config.messaging,
                ),
            ),
            install=partial(
                install_messaging,
                refresh_push_time_jobs=push_time_refresher,
                messaging=messaging,
            ),
            hooks=PluginHooks(
                startup=(
                    (
                        "messaging",
                        partial(messaging.start, scheduler),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="headless_notice",
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
                visible=partial(
                    _superuser_help_visible,
                    features=features,
                ),
            ),
            hooks=PluginHooks(
                startup=(
                    (
                        "headless_reconnect_jobs",
                        partial(register_reconnect_jobs, scheduler, headless),
                    ),
                ),
                first_bot_connect=(
                    (
                        "headless_seer_check",
                        check_headless_on_connect,
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="scheduled_restart",
            hooks=PluginHooks(
                startup=(
                    (
                        "scheduled_restart_jobs",
                        partial(
                            register_restart_jobs,
                            scheduler,
                            restart_times=(
                                tuple(config.operations.restart.parsed_restart_times)
                                if config.operations.restart.enabled
                                else ()
                            ),
                            grace_seconds=config.operations.restart.grace_seconds,
                            restart_process=partial(
                                terminate_bot_process,
                                signal_parent=(
                                    config.operations.restart.signal_parent
                                ),
                                reason="scheduled bot restart",
                            ),
                        ),
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
            install=partial(
                install_bilibili,
                service=bilibili_service,
                features=features,
                monitor=bili_monitor,
                targets=bilibili_service.targets,
            ),
            hooks=PluginHooks(
                startup=(
                    (
                        "bilibili_monitor_jobs",
                        partial(bili_monitor.register_job, scheduler),
                    ),
                ),
                first_bot_connect=(
                    (
                        "bilibili_check",
                        check_bilibili_on_connect,
                    ),
                ),
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
            install=partial(
                install_activity,
                service=activity_service,
                features=features,
            ),
            hooks=PluginHooks(
                startup=(
                    (
                        "activity_reminder_jobs",
                        partial(activity_service.register_jobs, scheduler),
                    ),
                ),
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
                visible=partial(
                    _feature_help_visible,
                    features=features,
                    feature="team_resource_subscription",
                    enabled=config.seer.team_resource.enabled,
                    group_only=True,
                ),
            ),
            install=partial(
                install_team_resource,
                service=team_resource_service,
            ),
            hooks=PluginHooks(
                startup=(
                    (
                        "team_resource_jobs",
                        partial(team_resource_service.register_jobs, scheduler),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="startup_notice",
            hooks=PluginHooks(
                first_bot_connect=(
                    (
                        "startup_notice",
                        partial(
                            send_startup_notice,
                            service=startup_notice_service,
                            config=config.operations.startup_notice,
                        ),
                    ),
                ),
            ),
        ),
        pet_config_definition(
            service=pet_config_service,
            features=features,
            config=config.pet_config,
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
            install=install_seer_query,
            hooks=PluginHooks(
                startup=(
                    (
                        "local_rank_jobs",
                        partial(
                            register_local_rank_refresh_job,
                            scheduler,
                            headless,
                            local_rank_service,
                        ),
                    ),
                    (
                        "rank_page_jobs",
                        partial(
                            register_rank_page_refresh_jobs,
                            scheduler,
                            headless,
                            rank_page_refresh_service,
                        ),
                    ),
                ),
                first_bot_connect=(("render_crash_report", report_render_crash),),
            ),
        ),
        PluginDefinition(
            id="team_audit",
            features=frozenset({Feature.TEAM_AUDIT}),
            install=partial(
                install_team_audit,
                scheduler=scheduler,
                service=team_audit_service,
            ),
            hooks=PluginHooks(
                bot_connect=(
                    (
                        "team_audit_followups",
                        partial(
                            team_audit_service.start,
                            scheduler=scheduler,
                        ),
                    ),
                ),
            ),
        ),
        PluginDefinition(
            id="fire_manual_ad",
            features=frozenset({Feature.FIRE_MANUAL_AD}),
        ),
        PluginDefinition(
            id="red_packet_notice",
            install=partial(
                install_red_packet_notice,
                config=config.messaging.red_packet_notice,
                admin_notices=admin_notices,
            ),
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
                visible=partial(
                    _feature_help_visible,
                    features=features,
                    feature="ai_chat",
                    enabled=bool(config.ai.api_key.strip()),
                ),
            ),
            install=partial(
                install_ai,
                service=ai_service,
                features=features,
                group_aliases=config.features.group_aliases,
                help_hint=help_hint_service,
            ),
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
                visible=partial(
                    _feature_help_visible,
                    features=features,
                    feature="ai_intent",
                    enabled=(
                        bool(config.ai.api_key.strip())
                        and config.ai.intent_actions_enabled
                    ),
                ),
            ),
            install=partial(
                install_ai_intent,
                service=ai_service,
                group_aliases=config.features.group_aliases,
                team_resource=team_resource_service,
            ),
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
                visible=_always_help_visible,
            ),
            install=install_about,
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
                visible=_always_help_visible,
            ),
            install=install_help,
        ),
        PluginDefinition(
            id="help_hint",
            install=partial(
                install_help_hint,
                service=help_hint_service,
            ),
        ),
        PluginDefinition(
            id="sendpic",
            features=frozenset({Feature.IMAGE}),
            install=install_sendpic,
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
            install=partial(
                install_meeting,
                commands=tuple(config.messaging.meeting.commands),
                number=config.messaging.meeting.number,
                template=config.messaging.meeting.template,
                features=features,
            ),
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
            install=partial(install_rank_help, features=features),
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
