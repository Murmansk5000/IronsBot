from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.cache import (
    get_dynamic_history_item,
    get_saved_cookie,
    list_dynamic_history,
    save_dynamic_history_snapshot,
)
from ironsbot.services.bilibili.client import fetch_dynamic_feed
from ironsbot.services.bilibili.menu import (
    DYNAMIC_IDS_STATE_KEY,
    build_dynamic_menu_text,
    dynamic_record_ids,
    select_cached_dynamic_id,
)
from ironsbot.services.bilibili.parser import (
    find_target_dynamics,
    parse_single_item,
)
from ironsbot.services.bilibili.permissions import (
    is_bili_superuser,
    is_dynamic_query_allowed,
    is_dynamic_update_allowed,
)
from ironsbot.services.bilibili.push import build_dynamic_history_snapshot_for_item
from ironsbot.services.bilibili.state import query_uids_for_event
from ironsbot.shared.messaging.text import command_text_matches, strip_command_prefix
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)

from .auth import send_bili_login_qrcode_to_superusers
from .config import get_bili_config
from .service import run_check_logic

DYNAMIC_CONVERSATION_NAMESPACE = "bilibili_dynamic_menu"
DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
DYNAMIC_SELECT_COMMANDS = tuple(str(number) for number in range(1, 11))
BILI_PLUGIN_NAME = "bili"


async def _is_dynamic_menu_command(event: MessageEvent) -> bool:
    if not is_dynamic_query_allowed(event):
        return False

    return command_text_matches(
        event.get_plaintext(),
        DYNAMIC_MENU_COMMANDS,
    )


async def _is_update_dynamic_command(event: MessageEvent) -> bool:
    command = strip_command_prefix(event.get_plaintext())
    if command is None:
        return False

    if not command_text_matches(
        command,
        DYNAMIC_UPDATE_COMMANDS,
    ):
        return False

    return is_dynamic_update_allowed(event)


def _is_dynamic_select_reply(event: MessageEvent) -> bool:
    return command_text_matches(event.get_plaintext(), DYNAMIC_SELECT_COMMANDS)


dynamic_menu_matcher = on_message(
    rule=Rule(_is_dynamic_menu_command),
    priority=1,
    block=True,
)

update_dynamic_matcher = on_message(
    rule=Rule(_is_update_dynamic_command),
    priority=1,
    block=True,
)


class BiliMonitorPlugin:
    name = BILI_PLUGIN_NAME
    feature = "bili_query"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "menu":
            await _handle_dynamic_menu(event, context)
            return
        if context.action == "update":
            await _handle_update_dynamic(event)
            return
        if context.action == "select":
            await _handle_dynamic_select(event, context)
            return


register_plugin(BiliMonitorPlugin())


async def _wait_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=DYNAMIC_CONVERSATION_NAMESPACE,
        handlers=[handle_dynamic_select],
        reply_check=_is_dynamic_select_reply,
    )


def _save_fetched_dynamics(target_dynamics: list[tuple[int, dict[str, Any]]]) -> None:
    for pub_ts, item in target_dynamics:
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=get_bili_config().filters.suppress_push_patterns,
        )
        if snapshot is not None:
            save_dynamic_history_snapshot(snapshot)


async def _handle_dynamic_menu(
    event: MessageEvent,
    context: PluginContext,
) -> None:
    matcher = context.matcher or dynamic_menu_matcher
    state = context.state if context.state is not None else {}
    try:
        query_uids = query_uids_for_event(event)
        if not query_uids:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 当前会话没有配置可查询的 B 站账号。",
            )

        await send_event_reply(
            dynamic_menu_matcher,
            event,
            "🔄 正在拉取 B 站动态...",
        )

        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if is_bili_auth_invalid(response.status_code, res_json):
            await send_bili_login_qrcode_to_superusers(
                "用户查询动态时发现 B 站登录失效"
            )
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "⚠️ B 站 Cookie 已失效，请超级管理员重新登录。",
            )

        items = res_json.get("data", {}).get("items", [])
        if items:
            target_dynamics = find_target_dynamics(items, query_uids)
            target_dynamics.sort(key=lambda value: value[0], reverse=True)
            _save_fetched_dynamics(target_dynamics)

        records = list_dynamic_history(limit=10, uids=query_uids)
        if not records:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 没有可展示的历史动态。",
            )

        state[DYNAMIC_IDS_STATE_KEY] = dynamic_record_ids(records)

        logger.info(
            f"user {event.user_id} fetched Bilibili dynamic menu for {query_uids}"
        )
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DYNAMIC_CONVERSATION_NAMESPACE,
            handlers=[handle_dynamic_select],
            reply_check=_is_dynamic_select_reply,
            prompt=Message(build_dynamic_menu_text(records)),
        )

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili dynamic menu failed: {e}")
        await finish_event_reply(
            dynamic_menu_matcher,
            event,
            "❌ 获取动态列表失败。",
        )


async def _handle_update_dynamic(event: MessageEvent) -> None:
    if not is_bili_superuser(event.user_id):
        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "❌ 仅超级管理员可用。",
        )

    try:
        logger.info(f"superuser {event.user_id} manually refreshed Bilibili")
        await send_event_reply(
            update_dynamic_matcher,
            event,
            "⚡ 正在刷新动态...",
        )

        did_run = await run_check_logic(is_startup_check=True, force=True)
        if not did_run:
            await finish_event_reply(
                update_dynamic_matcher,
                event,
                "⏳ 动态刷新正在进行中，请稍后再试。",
            )

        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "✅ 动态刷新完成。",
        )

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"manual Bilibili dynamic refresh failed: {e}")
        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "❌ 动态刷新失败。",
        )


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


async def _handle_dynamic_select(
    event: MessageEvent,
    context: PluginContext,
) -> None:
    matcher = context.matcher or dynamic_menu_matcher
    state = context.state if context.state is not None else {}
    try:
        cached_ids = state.get(DYNAMIC_IDS_STATE_KEY, [])
        selection = select_cached_dynamic_id(
            cached_ids,
            event.get_plaintext(),
        )
        if selection.status == "expired":
            await finish_event_reply(
                matcher,
                event,
                "⏳ 会话已超时，请重新发送“动态”。",
            )

        if selection.status == "invalid":
            await send_event_reply(
                matcher,
                event,
                "请输入数字。",
            )
            await _wait_dynamic_select(matcher, event)
            return

        if selection.status == "out_of_range":
            await send_event_reply(
                matcher,
                event,
                f"请输入 1~{selection.available_count} 之间的数字。",
            )
            await _wait_dynamic_select(matcher, event)
            return

        dynamic_id = selection.dynamic_id
        record = get_dynamic_history_item(dynamic_id)
        if record is None:
            await finish_event_reply(
                matcher,
                event,
                "❌ 没找到这条历史动态，请重新发送“动态”。",
            )

        final_message = parse_single_item(
            record.item,
            record.pub_ts,
            menu_mode=True,
            mode="full",
        )

        if final_message:
            await send_event_reply(
                matcher,
                event,
                final_message,
            )

        await _wait_dynamic_select(matcher, event)

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili dynamic number select failed: {e}")
        await finish_event_reply(
            matcher,
            event,
            "❌ 动态详情解析失败。",
        )


async def handle_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="select",
    )
