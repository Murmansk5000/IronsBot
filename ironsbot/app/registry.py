# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.app.command_directory.dynamic import (
    ai_intent_commands,
    configured_image_commands,
    configured_message_commands,
    messaging_help_visible,
)
from ironsbot.app.command_directory.operations import (
    data_sync_commands,
    docker_update_commands,
    server_status_commands,
)
from ironsbot.app.command_directory.plugins import (
    about_commands,
    activity_commands,
    ai_chat_commands,
    bilibili_commands,
    help_commands,
    meeting_commands,
    team_resource_commands,
)
from ironsbot.app.command_directory.seer import rank_commands, seer_query_commands
from ironsbot.app.external_plugins import external_install, load_external_plugin
from ironsbot.app.plugin_visibility import (
    always_help_visible,
    feature_help_visible,
    superuser_help_visible,
)
from ironsbot.core.features import Feature
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginDefinition,
    PluginHooks,
)
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.delivery import BilibiliPushDeliveryService
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from ironsbot.services.messaging.mention_guard import MentionGuardService
from ironsbot.services.operations.docker_preflight import (
    consume_docker_startup_preflight_notice,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.app.composition import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.runtime.matchers import MatcherRegistry


class PluginRegistryError(ValueError):
    pass


OPTIONAL_PRIVATE_FEATURES = frozenset(
    {
        Feature.PLAYER_LINEUP_PRIVATE,
    }
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
    from ironsbot.plugins.bilibili.delivery import (
        build_dynamic_content_message,
        build_dynamic_link_message,
    )
    from ironsbot.plugins.help.hint import install as install_help_hint
    from ironsbot.plugins.messaging.blacklist import install as install_blacklist
    from ironsbot.plugins.messaging.matchers import install as install_messaging
    from ironsbot.plugins.messaging.meeting import install as install_meeting
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
    from ironsbot.plugins.seer.lucky_skin_window import (
        plugin_definition as lucky_skin_window_plugin,
    )
    from ironsbot.plugins.seer.rank_help import install as install_rank_help
    from ironsbot.plugins.seer.runtime import (
        register_local_rank_refresh_job,
        register_rank_page_refresh_jobs,
    )
    from ironsbot.plugins.team import install as install_team_audit
    from ironsbot.plugins.team.resource import install as install_team_resource

    config = settings
    features = resources.features
    delivery = resources.delivery
    admin_notices = resources.admin_notices
    activity_service = resources.activity
    headless = resources.headless
    server_status = resources.server_status
    bilibili_service = resources.bilibili
    bilibili_login = resources.bilibili_login
    messaging = resources.messaging
    sendpic_service = resources.sendpic
    team_audit_service = resources.team_audit
    team_resource_service = resources.team_resource
    local_rank_service = resources.local_rank
    rank_page_refresh_service = resources.rank_page_refresh
    lucky_skin_window_service = resources.lucky_skin_window
    seer_resources = resources.seer
    pet_config_service = resources.pet_config
    ai_service = resources.ai
    data_sync_service = resources.data_sync
    docker_update_service = resources.docker_update
    startup_notice_service = resources.startup_notice
    help_hint_service = resources.help_hint
    mention_guard_service = MentionGuardService(config.messaging.command_cooldown)
    bili_notice_sender = partial(send_bili_login_notice, admin_notices)
    bili_auth_invalid = partial(
        bilibili_login.notify_required,
        send_notice=bili_notice_sender,
        is_online=lambda: delivery.default_bot() is not None,
    )
    bili_push_delivery = BilibiliPushDeliveryService(
        delivery,
        resources.subscriptions,
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        resources.push_message_limiter,
        getattr(ai_service, "summarize_bilibili_dynamic", None),
        config.bilibili.push.content_max_chars,
        config.bilibili.push.summary_max_chars,
        config.bilibili.push.summary_use_ai,
    )
    bili_monitor = BilibiliMonitorService(
        bilibili_service,
        bili_auth_invalid,
        bili_push_delivery.send,
    )
    messaging_commands = configured_message_commands(config.messaging)
    ai_intent_command_descriptors = ai_intent_commands(config)
    definitions: tuple[PluginDefinition, ...] = ()

    def install_scheduler(_registry: MatcherRegistry) -> None:
        load_external_plugin("nonebot_plugin_apscheduler")
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
                resources.commands,
                config.seer.new_content,
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
            resources.commands,
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
            install=external_install("nonebot_plugin_localstore"),
        ),
        PluginDefinition(
            id="htmlkit",
            install=external_install("nonebot_plugin_htmlkit"),
        ),
        PluginDefinition(
            id="saa",
            install=external_install("nonebot_plugin_saa"),
        ),
        PluginDefinition(
            id="conversation_blacklist",
            features=frozenset({Feature.BLACKLIST}),
            install=partial(install_blacklist, features=features),
        ),
        PluginDefinition(
            id="server_status",
            features=frozenset({Feature.SERVER_STATUS_QUERY}),
            help=HelpEntry(
                name="开服查询",
                description=(
                    "查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服"
                ),
                group="seer",
                order=70,
                notes=(
                    "无头客户端已登录游戏服务器时判定为已开服；公告仅作为维护信息摘要。",
                ),
            ),
            commands=server_status_commands(),
            install=partial(
                install_server_status,
                docker_service=docker_update_service,
                server_status=server_status,
                features=features,
                commands=resources.commands,
            ),
            hooks=PluginHooks(
                startup=(("docker_update", start_docker_update),),
            ),
        ),
        PluginDefinition(
            id="db_sync",
            help=HelpEntry(
                name="数据更新",
                description="构建并同步赛尔数据库与别名数据库",
                group="admin",
                order=20,
                visible=partial(
                    superuser_help_visible,
                    features=features,
                ),
            ),
            commands=data_sync_commands(),
            install=partial(
                install_db_sync,
                service=data_sync_service,
            ),
            hooks=PluginHooks(
                startup=(("db_sync", start_data_sync),),
            ),
        ),
        PluginDefinition(
            id="docker_update",
            help=HelpEntry(
                name="镜像维护",
                description="检查 Docker 镜像、更新镜像或重启机器人",
                group="admin",
                order=10,
                visible=partial(
                    superuser_help_visible,
                    features=features,
                ),
            ),
            commands=docker_update_commands(),
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
                group="message",
                order=30,
                visible=partial(
                    messaging_help_visible,
                    features=features,
                    config=config.messaging,
                ),
            ),
            commands=messaging_commands,
            install=partial(
                install_messaging,
                refresh_push_time_jobs=push_time_refresher,
                messaging=messaging,
                command_help_ids=tuple(
                    command.id
                    for command in messaging_commands
                    if command.interaction == "direct"
                ),
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
                                signal_parent=(config.operations.restart.signal_parent),
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
                description="查询、刷新和自动推送已订阅 UID 的 Bilibili 动态",
                group="message",
                order=20,
            ),
            commands=bilibili_commands(),
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
                group="message",
                order=10,
                notes=("自动提醒时间由 activity.lead_hours 配置。",),
            ),
            commands=activity_commands(),
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
                description="订阅战队，并在资源不足时定时提醒当前会话。",
                group="seer",
                order=50,
                visible=partial(
                    feature_help_visible,
                    features=features,
                    feature="team_resource_subscription",
                    enabled=config.seer.team_resource.enabled,
                ),
            ),
            commands=team_resource_commands(enabled=config.seer.team_resource.enabled),
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
                group="seer",
                order=10,
            ),
            commands=seer_query_commands(),
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
                group="ai",
                order=10,
                visible=partial(
                    feature_help_visible,
                    features=features,
                    feature="ai_chat",
                    enabled=bool(config.ai.api_key.strip()),
                ),
            ),
            commands=ai_chat_commands(enabled=bool(config.ai.api_key.strip())),
            install=(
                partial(
                    install_ai,
                    service=ai_service,
                    features=features,
                    group_aliases=config.features.group_aliases,
                    mention_guard_service=mention_guard_service,
                )
                if config.ai.api_key.strip()
                else None
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
                group="ai",
                order=20,
                visible=partial(
                    feature_help_visible,
                    features=features,
                    feature="ai_intent",
                    enabled=(
                        bool(config.ai.api_key.strip())
                        and config.ai.intent_actions_enabled
                    ),
                ),
            ),
            commands=ai_intent_command_descriptors,
            install=partial(
                install_ai_intent,
                service=ai_service,
                group_aliases=config.features.group_aliases,
                team_resource=team_resource_service,
                command_help_ids=tuple(
                    command.id for command in ai_intent_command_descriptors
                ),
            ),
        ),
        PluginDefinition(
            id="about",
            features=frozenset({Feature.ABOUT}),
            help=HelpEntry(
                name="关于",
                description="IronsBot 项目信息与当前版本",
                group="core",
                order=20,
                visible=always_help_visible,
            ),
            commands=about_commands(),
            install=install_about,
        ),
        PluginDefinition(
            id="help",
            features=frozenset({Feature.HELP}),
            help=HelpEntry(
                name="帮助",
                description="按当前群/私聊权限显示可用功能",
                group="core",
                order=10,
                visible=always_help_visible,
            ),
            commands=help_commands(),
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
            help=HelpEntry(
                name="图片发送",
                description="发送固定图片或配置的图片库内容",
                group="other",
                order=20,
            ),
            commands=configured_image_commands(config),
            install=install_sendpic,
        ),
        PluginDefinition(
            id="meeting",
            features=frozenset({Feature.MEETING}),
            help=HelpEntry(
                name="会议回复",
                description="按配置回复腾讯会议信息",
                group="message",
                order=40,
            ),
            commands=meeting_commands(config),
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
                group="seer",
                order=20,
            ),
            commands=rank_commands(),
            install=partial(
                install_rank_help,
                features=features,
                commands=resources.commands,
            ),
        ),
        lucky_skin_window_plugin(
            lucky_skin_window_service,
            features,
            delivery,
            scheduler,
        ),
    )
    private_definitions = resources.private_extensions.load_plugin_definitions(
        resources.private_extension_runtime
    )
    definitions = (*definitions, *private_definitions)
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
        set(Feature) - owned_features - OPTIONAL_PRIVATE_FEATURES,
        key=lambda feature: feature.value,
    )
    if missing:
        raise PluginRegistryError(
            "features have no owning plugin: "
            + ", ".join(feature.value for feature in missing)
        )
