from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.matcher_priority import get_matcher_priority
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


def install(registry: MatcherRegistry) -> None:
    dynamic_menu = registry.on_message(
        policy=CommandPolicy.command("bili_query"),
        rule=Rule(is_dynamic_menu_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    dynamic_menu.append_handler(handle_dynamic_menu_action)

    update_dynamic = registry.on_message(
        policy=CommandPolicy.command("bili_refresh"),
        rule=Rule(is_update_dynamic_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    update_dynamic.append_handler(handle_update_dynamic_action)

    bili_account = registry.on_message(
        policy=CommandPolicy.command("bili_accounts"),
        rule=Rule(is_bili_account_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    bili_account.append_handler(handle_bili_accounts_action)

    push_mode = registry.on_message(
        policy=CommandPolicy.command("bili_push_mode"),
        rule=Rule(is_bili_push_mode_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    push_mode.append_handler(handle_bili_push_mode_action)
