from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.portable_bilibili_commands import (
    build_portable_bilibili_operations,
)

from .command_rules import matches_bilibili_command

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContract
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions


def _rule(contract: CommandContract, features: FeatureService) -> Rule:
    def matches(event: MessageEvent) -> bool:
        return matches_bilibili_command(contract.id, features, event)

    return Rule(matches) & explicit_command()


def install(  # noqa: PLR0913 - transport composition
    registry: MatcherFactory,
    service: BilibiliService,
    features: FeatureService,
    monitor: BilibiliMonitorService,
    targets: BiliTargetService,
    query_sessions: PortableQuerySessions,
) -> None:
    del targets
    operations = build_portable_bilibili_operations(
        service,
        query_sessions,
        notify_auth_invalid=monitor.notify_auth_invalid,
        refresh_now=monitor.manual_refresh,
        features=features,
    )
    for contract in bilibili_command_contracts():
        matcher = registry.on_message(
            policy=CommandPolicy.command(contract.id, help_ids=(contract.id,)),
            rule=_rule(contract, features),
            priority=registry.priority("bilibili"),
            block=True,
        )
        matcher.append_handler(
            make_portable_query_handler(operations[contract.id], query_sessions)
        )
