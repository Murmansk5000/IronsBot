from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.rules import no_reply

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
        policy=CommandPolicy.command("bili_query"),
        rule=Rule(partial(is_dynamic_menu_command, features)) & no_reply(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    dynamic_menu.append_handler(
        partial(
            handle_dynamic_menu_action,
            service=service,
            monitor=monitor,
        )
    )

    update_dynamic = registry.on_message(
        policy=CommandPolicy.command("bili_refresh"),
        rule=Rule(partial(is_update_dynamic_command, features)) & no_reply(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    update_dynamic.append_handler(
        partial(
            handle_update_dynamic_action,
            features=features,
            monitor=monitor,
        )
    )

    bili_account = registry.on_message(
        policy=CommandPolicy.command("bili_accounts"),
        rule=Rule(partial(is_bili_account_command, features)) & no_reply(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    bili_account.append_handler(
        partial(handle_bili_accounts_action, targets=targets)
    )

    push_mode = registry.on_message(
        policy=CommandPolicy.command("bili_push_mode"),
        rule=Rule(is_bili_push_mode_command) & no_reply(),
        priority=registry.priority("bilibili"),
        block=True,
    )
    push_mode.append_handler(
        partial(
            handle_bili_push_mode_action,
            features=features,
            targets=targets,
        )
    )
