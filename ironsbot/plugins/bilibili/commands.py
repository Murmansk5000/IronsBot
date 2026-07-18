from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

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
from .dynamic_actions import (
    handle_dynamic_menu_action,
)
from .update_actions import handle_update_dynamic_action


async def handle_dynamic_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await handle_dynamic_menu_action(matcher, event, state)


async def handle_update_dynamic(matcher: Matcher, event: MessageEvent) -> None:
    await handle_update_dynamic_action(matcher, event)


async def handle_bili_account(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await handle_bili_accounts_action(matcher, event)


async def handle_bili_push_mode(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await handle_bili_push_mode_action(matcher, event, state)


def install(registry: MatcherRegistry) -> None:
    dynamic_menu = registry.on_message(
        policy=CommandPolicy.command("bili_query"),
        rule=Rule(is_dynamic_menu_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    dynamic_menu.append_handler(handle_dynamic_menu)

    update_dynamic = registry.on_message(
        policy=CommandPolicy.command("bili_refresh"),
        rule=Rule(is_update_dynamic_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    update_dynamic.append_handler(handle_update_dynamic)

    bili_account = registry.on_message(
        policy=CommandPolicy.command("bili_accounts"),
        rule=Rule(is_bili_account_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    bili_account.append_handler(handle_bili_account)

    push_mode = registry.on_message(
        policy=CommandPolicy.command("bili_push_mode"),
        rule=Rule(is_bili_push_mode_command) & no_reply(),
        priority=get_matcher_priority("bilibili", 1),
        block=True,
    )
    push_mode.append_handler(handle_bili_push_mode)
