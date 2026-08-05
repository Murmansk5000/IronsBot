# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.integrations.onebot.identity import onebot_actor_ref
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.replies import finish_event_reply, send_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.services.operations.data_sync_commands import (
    data_sync_command_contracts,
    is_force_data_sync_command,
    is_manual_data_sync_command,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.operations.startup import StartupNoticeService

__plugin_meta__ = PluginMetadata(
    name="数据更新",
    description="构建远程数据并同步赛尔数据库与别名数据库。",
    usage="超级管理员发送“/更新数据”或“/强制更新数据”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

def _help_visible(event: Event, *, features: FeatureService) -> bool:
    if isinstance(event, GroupMessageEvent):
        return False
    user_id = getattr(event, "user_id", None)
    return user_id is not None and features.is_actor_superuser(
        onebot_actor_ref(str(user_id))
    )


async def _start_data_sync(
    *,
    service: DataSyncService,
    startup_notice: StartupNoticeService,
    scheduler: Scheduler,
) -> None:
    startup_notice.add(
        "startup_data_sync",
        "startup data sync notice",
        await service.startup(scheduler),
    )


async def _is_manual_sync_command(event: Event) -> bool:
    return is_manual_data_sync_command(event.get_plaintext())


def _is_force_manual_sync_event(event: Event) -> bool:
    return is_force_data_sync_command(event.get_plaintext())


def _install(registry: MatcherFactory, service: DataSyncService) -> None:
    async def handle_sync(matcher: Matcher, event: MessageEvent) -> None:
        force = _is_force_manual_sync_event(event)
        message, should_run = service.prepare_manual(force=force)
        if not should_run:
            await finish_event_reply(
                matcher,
                event,
                message,
            )
        await send_event_reply(matcher, event, message)
        await finish_event_reply(
            matcher,
            event,
            await service.run_manual(force=force),
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            "data_sync",
            help_ids=("db_sync.update", "db_sync.force_update"),
        ),
        rule=Rule(_is_manual_sync_command) & explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("db_sync"),
        block=True,
    )
    matcher.append_handler(handle_sync)


def plugin_contribution(
    *,
    service: DataSyncService,
    features: FeatureService,
    startup_notice: StartupNoticeService,
    scheduler: Scheduler,
) -> PluginContribution:
    """Declare admin data-sync commands and the configured startup sync."""

    return PluginContribution(
        id="db_sync",
        help=HelpEntry(
            name="数据更新",
            description="构建并同步赛尔数据库与别名数据库",
            group="admin",
            order=20,
            visible=partial(_help_visible, features=features),
        ),
        commands=data_sync_command_contracts(),
        install=partial(_install, service=service),
        hooks=PluginHooks(
            startup=(
                (
                    "db_sync",
                    partial(
                        _start_data_sync,
                        service=service,
                        startup_notice=startup_notice,
                        scheduler=scheduler,
                    ),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.data_sync,
            features=context.resources.features,
            startup_notice=context.resources.startup_notice,
            scheduler=context.scheduler,
        ),
    )
