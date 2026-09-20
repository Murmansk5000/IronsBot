# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.conversations import enter_event_reply_conversation
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.replies import finish_event_reply, send_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.data_sync_commands import (
    data_sync_command_contracts,
    is_force_data_sync_command,
    is_manual_data_sync_command,
)

if TYPE_CHECKING:
    from nonebot.typing import T_State

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.data_sync import DataSyncService

__plugin_meta__ = PluginMetadata(
    name="数据更新",
    description="构建远程数据并同步赛尔数据库与别名数据库。",
    usage="超级管理员发送“/更新数据”或“/强制更新数据”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

DATA_SYNC_FORCE_STATE_KEY = "data_sync_force"
DATA_SYNC_ACTION_NAMESPACE = "data_sync_action"


async def _is_manual_sync_command(event: Event) -> bool:
    return is_manual_data_sync_command(event.get_plaintext())


def _is_force_manual_sync_event(event: Event) -> bool:
    return is_force_data_sync_command(event.get_plaintext())


def _install(registry: MatcherFactory, service: DataSyncService) -> None:
    async def handle_sync(matcher: Matcher, event: MessageEvent) -> None:
        force = _is_force_manual_sync_event(event)
        message, should_run = await service.prepare_manual(
            force=force,
            progress=partial(send_event_reply, matcher, event),
        )
        if not should_run:
            await finish_event_reply(
                matcher,
                event,
                message,
            )
            return
        matcher.state[DATA_SYNC_FORCE_STATE_KEY] = force
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DATA_SYNC_ACTION_NAMESPACE,
            handlers=[bind_async(handle_sync_action)],
            reply_check=lambda reply: _is_manual_action_reply(reply, service),
            prompt=message,
        )

    async def handle_sync_action(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        choice = event.get_plaintext().strip()
        if choice == "0":
            await finish_event_reply(matcher, event, "已取消更新。")
            return
        force = bool(state.get(DATA_SYNC_FORCE_STATE_KEY, False))
        action = service.manual_action_for_choice(choice, force=force)
        if action is None:
            await finish_event_reply(
                matcher,
                event,
                "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
            )
            return
        await finish_event_reply(
            matcher,
            event,
            await service.run_manual(
                action=action,
                force=force,
                progress=partial(send_event_reply, matcher, event),
            ),
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


def _is_manual_action_reply(event: MessageEvent, service: DataSyncService) -> bool:
    choice = event.get_plaintext().strip()
    return choice == "0" or (
        service.manual_action_for_choice(choice, force=False) is not None
    )


def plugin_contribution(
    *,
    service: DataSyncService,
    features: FeatureService,
) -> PluginContribution:
    """Declare the OneBot administrator commands for application-owned sync."""

    return PluginContribution(
        id="db_sync",
        help=HelpEntry(
            name="数据更新",
            description="构建并同步赛尔数据库与别名数据库",
            group="admin",
            order=20,
            visible=partial(superuser_help_visible, features=features),
        ),
        commands=data_sync_command_contracts(),
        install=partial(_install, service=service),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.data_sync,
            features=context.resources.features,
        ),
    )
