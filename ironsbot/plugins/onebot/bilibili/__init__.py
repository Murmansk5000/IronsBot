# SPDX-License-Identifier: MIT
"""OneBot Bilibili command, monitor, and manifest integration."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.integrations.onebot.bilibili_push import OneBotBilibiliPushSender
from ironsbot.runtime.commands import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.runtime import BilibiliMonitorService

from .auth import send_bili_login_notice
from .command_rules import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
)
from .commands import install
from .delivery import build_dynamic_content_message, build_dynamic_link_message

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.login import BilibiliLoginService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.delivery import MessageDelivery, MessageLimiter
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.operations.scheduler import Scheduler

__plugin_meta__ = PluginMetadata(
    name="B站动态",
    description="查询、刷新和自动推送已订阅 UID 的 Bilibili 动态。",
    usage="发送“动态”查询已订阅账号的动态。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def command_descriptors() -> tuple[CommandDescriptor, ...]:
    return (
        *commands_from_rows(
            "bilibili",
            "查询",
            "bili_query",
            (
                (
                    "bilibili.dynamic",
                    DYNAMIC_MENU_COMMANDS[:1],
                    "查看订阅账号的最新动态",
                    {"show_in_poke": True},
                ),
                (
                    "bilibili.accounts",
                    BILI_ACCOUNT_COMMANDS[:1],
                    "查看当前会话订阅的账号",
                    {
                        "features_any": (),
                        "access": (
                            CommandAccess(features_any=("bili_query",)),
                            CommandAccess(
                                "group",
                                "group_manager",
                                ("bili_push",),
                            ),
                            CommandAccess("private", features_any=("bili_push",)),
                        ),
                    },
                ),
            ),
        ),
        *commands_from_rows(
            "bilibili",
            "本群管理",
            "bili_push",
            (
                (
                    "bilibili.push_mode",
                    tuple(
                        f"{command} <账号> <内容|链接|默认>"
                        for command in BILI_PUSH_MODE_COMMANDS[:1]
                    ),
                    "调整当前会话指定账号的推送模式",
                    {"access": (CommandAccess("group", "group_manager"),)},
                ),
            ),
        ),
        *commands_from_rows(
            "bilibili",
            "私聊管理",
            "bili_push",
            (
                (
                    "bilibili.private_push_mode",
                    tuple(
                        f"{command} <账号> <内容|链接|默认>"
                        for command in BILI_PUSH_MODE_COMMANDS[:1]
                    ),
                    "调整当前私聊订阅账号的推送模式",
                    {"access": (CommandAccess("private"),)},
                ),
            ),
        ),
        *commands_from_rows(
            "bilibili",
            "超级管理员",
            "bili_push",
            (
                (
                    "bilibili.refresh",
                    tuple(f"/{command}" for command in DYNAMIC_UPDATE_COMMANDS[:1]),
                    "立即刷新订阅动态",
                    {
                        "access": (CommandAccess(audience="superuser"),),
                        "routing_aliases": DYNAMIC_UPDATE_COMMANDS,
                    },
                ),
            ),
        ),
    )


def _build_monitor(  # noqa: PLR0913 - Bilibili integration dependencies
    *,
    service: BilibiliService,
    login: BilibiliLoginService,
    delivery: MessageDelivery,
    subscriptions: PushSubscriptionRepository,
    admin_notices: AdminNoticeService,
    message_limiter: MessageLimiter,
    ai_service: AiService,
    config: BiliConfig,
) -> BilibiliMonitorService:
    notice_sender = partial(send_bili_login_notice, admin_notices)
    auth_invalid = partial(
        login.notify_required,
        send_notice=notice_sender,
        is_online=lambda: delivery.default_bot() is not None,
    )
    push_delivery = OneBotBilibiliPushSender(
        delivery,
        subscriptions,
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        message_limiter,
        getattr(ai_service, "summarize_bilibili_dynamic", None),
        config.push.content_max_chars,
        config.push.summary_max_chars,
        config.push.summary_use_ai,
        service.targets.can_conversation_query_history,
        admin_notices,
    )
    return BilibiliMonitorService(service, auth_invalid, push_delivery.send)


async def _check_on_connect(bot: Bot, *, monitor: BilibiliMonitorService) -> None:
    await monitor.check_on_connect(str(bot.self_id))


def plugin_contribution(  # noqa: PLR0913
    *,
    service: BilibiliService,
    login: BilibiliLoginService,
    features: FeatureService,
    config: BiliConfig,
    delivery: MessageDelivery,
    subscriptions: PushSubscriptionRepository,
    admin_notices: AdminNoticeService,
    message_limiter: MessageLimiter,
    ai_service: AiService,
    scheduler: Scheduler,
) -> PluginContribution:
    """Declare Bilibili commands, delivery construction, and monitor lifecycle."""

    monitor = _build_monitor(
        service=service,
        login=login,
        delivery=delivery,
        subscriptions=subscriptions,
        admin_notices=admin_notices,
        message_limiter=message_limiter,
        ai_service=ai_service,
        config=config,
    )
    return PluginContribution(
        id="bilibili",
        features=frozenset({Feature.BILI_QUERY, Feature.BILI_PUSH}),
        help=HelpEntry(
            name="B站动态",
            description="查询、刷新和自动推送已订阅 UID 的 Bilibili 动态",
            group="message",
            order=20,
        ),
        commands=command_descriptors(),
        install=partial(
            install,
            service=service,
            features=features,
            monitor=monitor,
            targets=service.targets,
        ),
        hooks=PluginHooks(
            startup=(
                (
                    "bilibili_monitor_jobs",
                    partial(monitor.register_job, scheduler),
                ),
            ),
            first_bot_connect=(
                (
                    "bilibili_check",
                    partial(_check_on_connect, monitor=monitor),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.bilibili,
            login=context.resources.bilibili_login,
            features=context.resources.features,
            config=context.settings.bilibili,
            delivery=context.resources.delivery,
            subscriptions=context.resources.subscriptions,
            admin_notices=context.resources.admin_notices,
            message_limiter=context.resources.push_message_limiter,
            ai_service=context.resources.ai,
            scheduler=context.scheduler,
        ),
    )
