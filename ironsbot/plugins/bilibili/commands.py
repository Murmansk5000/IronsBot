from functools import partial

from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.messaging.admin_notice import AdminNoticeService
from ironsbot.utils.rule import no_reply

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


def install(
    registry: MatcherRegistry,
    admin_notices: AdminNoticeService,
) -> None:
    features = admin_notices.features
    dynamic_menu = registry.on_message(
        policy=CommandPolicy.command("bili_query"),
        rule=Rule(partial(is_dynamic_menu_command, features)) & no_reply(),
        priority=registry.priority("bilibili", 1),
        block=True,
    )
    dynamic_menu.append_handler(
        partial(
            handle_dynamic_menu_action,
            admin_notices=admin_notices,
        )
    )

    update_dynamic = registry.on_message(
        policy=CommandPolicy.command("bili_refresh"),
        rule=Rule(partial(is_update_dynamic_command, features)) & no_reply(),
        priority=registry.priority("bilibili", 1),
        block=True,
    )
    update_dynamic.append_handler(
        partial(
            handle_update_dynamic_action,
            admin_notices=admin_notices,
        )
    )

    bili_account = registry.on_message(
        policy=CommandPolicy.command("bili_accounts"),
        rule=Rule(partial(is_bili_account_command, features)) & no_reply(),
        priority=registry.priority("bilibili", 1),
        block=True,
    )
    bili_account.append_handler(
        partial(handle_bili_accounts_action, features=features)
    )

    push_mode = registry.on_message(
        policy=CommandPolicy.command("bili_push_mode"),
        rule=Rule(is_bili_push_mode_command) & no_reply(),
        priority=registry.priority("bilibili", 1),
        block=True,
    )
    push_mode.append_handler(
        partial(handle_bili_push_mode_action, features=features)
    )
