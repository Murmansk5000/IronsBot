from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .account_commands import (
    handle_bili_accounts_action,
    handle_bili_push_mode_action,
)
from .command_context import BILI_PLUGIN_NAME
from .command_rules import (
    is_bili_account_command,
    is_bili_push_mode_command,
    is_dynamic_menu_command,
    is_update_dynamic_command,
)
from .dynamic_actions import (
    handle_dynamic_menu_action,
    handle_dynamic_select_action,
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


class BiliMonitorPlugin:
    name = BILI_PLUGIN_NAME
    feature = "bili_query"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "menu":
            await handle_dynamic_menu_action(event, context, dynamic_menu_matcher)
            return
        if context.action == "update":
            await handle_update_dynamic_action(event, update_dynamic_matcher)
            return
        if context.action == "select":
            await handle_dynamic_select_action(event, context, dynamic_menu_matcher)
            return
        if context.action == "accounts":
            await handle_bili_accounts_action(event, context, bili_account_matcher)
            return
        if context.action == "push_mode":
            await handle_bili_push_mode_action(event, context, bili_push_mode_matcher)
            return


register_plugin(BiliMonitorPlugin())


@dynamic_menu_matcher.handle()
async def handle_dynamic_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="menu",
    )


@update_dynamic_matcher.handle()
async def handle_update_dynamic(event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=update_dynamic_matcher,
        action="update",
    )


@bili_account_matcher.handle()
async def handle_bili_account(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="accounts",
    )


@bili_push_mode_matcher.handle()
async def handle_bili_push_mode(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="push_mode",
    )
