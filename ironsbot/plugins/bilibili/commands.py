from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind, bind_async
from ironsbot.runtime.rules import explicit_command

from .account_commands import (
    handle_bili_accounts_action,
    handle_bili_push_mode_action,
)
from .command_rules import (
    is_bili_account_command,
    is_bili_push_mode_command,
    is_dynamic_menu_command,
    is_update_dynamic_command,
)
from .dynamic_actions import handle_dynamic_menu_action
from .update_actions import handle_update_dynamic_action

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.bilibili.targets import BiliTargetService


def install(
    registry: MatcherRegistry,
    service: BilibiliService,
    features: FeatureService,
    monitor: BilibiliMonitorService,
    targets: BiliTargetService,
) -> None:
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
            handle_update_dynamic_action,
            features=features,
            monitor=monitor,
        )
    )

    bili_account = registry.on_message(
        policy=CommandPolicy.command("bili_accounts", help_ids=("bilibili.accounts",)),
        rule=Rule(bind(is_bili_account_command, features)) & explicit_command(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    bili_account.append_handler(
        bind_async(handle_bili_accounts_action, targets=targets)
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
            handle_bili_push_mode_action,
            features=features,
            targets=targets,
        )
    )
