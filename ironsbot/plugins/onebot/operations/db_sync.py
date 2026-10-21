# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
)
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_query_handler,
    portable_contract_rule,
)
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.data_sync_commands import (
    data_sync_command_contracts,
    is_force_data_sync_command,
    is_manual_data_sync_command,
)
from ironsbot.services.portable_operational_commands import (
    build_portable_data_sync_operations,
)
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions

__plugin_meta__ = PluginMetadata(
    name="数据更新",
    description="构建远程数据并同步赛尔数据库与别名数据库。",
    usage="超级管理员发送“/更新数据”或“/强制更新数据”；也支持“/同步数据”和“/强制同步数据”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def _is_manual_sync_command(event: Event) -> bool:
    return is_manual_data_sync_command(event.get_plaintext())


def _install(
    registry: MatcherFactory,
    service: DataSyncService,
    query_sessions: PortableQuerySessions,
    features: FeatureService,
) -> None:
    operations = build_portable_data_sync_operations(service, query_sessions)

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        command = (
            "db_sync.force_update"
            if is_force_data_sync_command(text)
            else "db_sync.update"
        )
        result = await operations[command](text, context)
        assert isinstance(result, PortableReply)
        return result

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            "data_sync",
            help_ids=("db_sync.update", "db_sync.force_update"),
        ),
        rule=Rule(_is_manual_sync_command)
        & explicit_command()
        & portable_contract_rule(data_sync_command_contracts()[0], features),
        priority=registry.priority("db_sync"),
        block=True,
    )
    matcher.append_handler(make_portable_query_handler(execute, query_sessions))


def plugin_contribution(
    *,
    service: DataSyncService,
    features: FeatureService,
    query_sessions: PortableQuerySessions,
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
        install=partial(
            _install, service=service, query_sessions=query_sessions, features=features
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.data_sync,
            features=context.resources.features,
            query_sessions=context.resources.query_sessions,
        ),
    )
