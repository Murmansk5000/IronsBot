# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Bot  # noqa: TC002
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from ironsbot.config.models.operations import StartupConfig
    from ironsbot.services.messaging.admin_notice import AdminNoticeSendSummary
    from ironsbot.services.operations.startup import StartupNoticeService

__plugin_meta__ = PluginMetadata(
    name="启动通知",
    description="在首个机器人连接后汇总发送启动状态通知。",
    usage="后台运行插件，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def _send_notice_part(
    *,
    service: StartupNoticeService,
    message_text: str,
    subscription_key: str,
    action_name: str,
) -> AdminNoticeSendSummary:
    return await service.admin_notices.send(
        message_text,
        action_name=action_name,
        subscription_key=subscription_key,
    )


async def send_startup_notice(
    _bot: Bot,
    service: StartupNoticeService,
    config: StartupConfig,
) -> None:
    if not service.should_send(enabled=config.enabled):
        return

    service.begin_send()

    try:
        targets = service.admin_notices.targets()
        if targets.is_empty:
            logger.warning("startup notice has no admin notice targets")
            return

        if config.delay > 0:
            await asyncio.sleep(config.delay)

        summaries: list[AdminNoticeSendSummary] = []
        summaries.append(
            await _send_notice_part(
                message_text=config.message,
                service=service,
                subscription_key="startup_notice",
                action_name="startup notice",
            )
        )
        summaries.extend(
            [
                await _send_notice_part(
                    message_text=part.message,
                    service=service,
                    subscription_key=part.subscription_key,
                    action_name=part.action_name,
                )
                for part in service.parts
            ]
        )
        succeeded = [target for summary in summaries for target in summary.succeeded]

        service.mark_result(succeeded)
        if service.sent:
            logger.info(
                "startup notice sent to {} targets in {} parts",
                len(set(succeeded)),
                len(summaries),
            )
    finally:
        service.finish_send()


def plugin_contribution(
    *,
    service: StartupNoticeService,
    config: StartupConfig,
) -> PluginContribution:
    """Declare the first-connection startup notice lifecycle hook."""

    return PluginContribution(
        id="startup_notice",
        hooks=PluginHooks(
            first_bot_connect=(
                (
                    "startup_notice",
                    partial(send_startup_notice, service=service, config=config),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.startup_notice,
            config=context.settings.operations.startup_notice,
        ),
    )
