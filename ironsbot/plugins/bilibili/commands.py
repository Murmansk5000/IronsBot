from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

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

dynamic_menu_matcher = on_message(
    rule=Rule(is_dynamic_menu_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)

update_dynamic_matcher = on_message(
    rule=Rule(is_update_dynamic_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)

bili_account_matcher = on_message(
    rule=Rule(is_bili_account_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)

bili_push_mode_matcher = on_message(
    rule=Rule(is_bili_push_mode_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)


@dynamic_menu_matcher.handle()
async def handle_dynamic_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await handle_dynamic_menu_action(matcher, event, state)


@update_dynamic_matcher.handle()
async def handle_update_dynamic(matcher: Matcher, event: MessageEvent) -> None:
    await handle_update_dynamic_action(matcher, event)


@bili_account_matcher.handle()
async def handle_bili_account(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await handle_bili_accounts_action(matcher, event)


@bili_push_mode_matcher.handle()
async def handle_bili_push_mode(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await handle_bili_push_mode_action(matcher, event, state)
