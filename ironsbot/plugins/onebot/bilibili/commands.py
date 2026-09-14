from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind,
    bind_async,
)
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_bilibili_commands import (
    build_portable_bilibili_management_operations,
)

from .command_rules import (
    is_bili_account_command,
    is_bili_push_mode_command,
    is_dynamic_menu_command,
    is_update_dynamic_command,
)
from .dynamic_actions import handle_dynamic_menu_action

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService

def install(
    registry: MatcherFactory,
    service: BilibiliService,
    features: FeatureService,
    monitor: BilibiliMonitorService,
) -> None:
    async def refresh_now() -> str:
        return await monitor.manual_refresh()

    operations = build_portable_bilibili_management_operations(
        service,
        features,
        refresh_now=refresh_now,
    )
    dynamic_menu = registry.on_message(
        policy=CommandPolicy.command("bili_query", help_ids=("bilibili.dynamic",)),
        rule=Rule(bind(is_dynamic_menu_command, features)) & explicit_command(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    dynamic_menu.append_handler(
        bind_async(
            handle_dynamic_menu_action,
            service=service,
            monitor=monitor,
        )
    )

    update_dynamic = registry.on_message(
        policy=CommandPolicy.command("bili_refresh", help_ids=("bilibili.refresh",)),
        rule=Rule(bind(is_update_dynamic_command, features)) & explicit_command(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    update_dynamic.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["bilibili.refresh"],
        )
    )

    bili_account = registry.on_message(
        policy=CommandPolicy.command("bili_accounts", help_ids=("bilibili.accounts",)),
        rule=Rule(bind(is_bili_account_command, features)) & explicit_command(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    bili_account.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["bilibili.accounts"],
        )
    )

    push_mode = registry.on_message(
        policy=CommandPolicy.command(
            "bili_push_mode",
            help_ids=("bilibili.push_mode", "bilibili.private_push_mode"),
        ),
        rule=Rule(bind(is_bili_push_mode_command, features)) & explicit_command(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    push_mode.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["bilibili.push_mode"],
        )
    )
