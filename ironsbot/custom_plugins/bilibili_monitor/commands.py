from datetime import datetime, timezone
from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)

from .auth import is_bili_auth_invalid, send_bili_login_qrcode_to_superusers
from .cache import get_saved_cookie, save_dynamic_history_item
from .client import fetch_dynamic_feed
from .parser import (
    dynamic_brief,
    find_target_dynamics,
    item_author_label,
    item_author_mid,
    item_author_name,
    item_pub_ts,
    parse_single_item,
)
from .permissions import (
    is_bili_superuser,
    is_dynamic_query_allowed,
    is_dynamic_update_allowed,
)
from .service import run_check_logic

DYNAMIC_ITEMS_KEY = "_bilibili_dynamic_items"
DYNAMIC_CONVERSATION_NAMESPACE = "bilibili_dynamic_menu"
DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
DYNAMIC_SELECT_COMMANDS = tuple(str(number) for number in range(1, 11))
DYNAMIC_MENU_TIMEOUT_SECONDS = 120
ADMIN_COMMAND_PREFIX = "/"


def _strip_admin_command_prefix(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith(ADMIN_COMMAND_PREFIX):
        return None

    return stripped[len(ADMIN_COMMAND_PREFIX) :].strip()


async def _is_dynamic_menu_command(event: MessageEvent) -> bool:
    if not is_dynamic_query_allowed(event):
        return False

    return command_text_matches(
        event.get_plaintext(),
        DYNAMIC_MENU_COMMANDS,
    )


async def _is_update_dynamic_command(event: MessageEvent) -> bool:
    command = _strip_admin_command_prefix(event.get_plaintext())
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

def _build_menu_text(menu_list: list[tuple[int, dict[str, Any]]]) -> str:
    reply_text = (
        "📋 【最新动态列表】\n"
        "👉 发送数字查看详情\n"
        "-------------------------\n"
    )

    for index, (pub_ts, item) in enumerate(menu_list, start=1):
        time_str = (
            datetime.fromtimestamp(pub_ts, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        reply_text += (
            f"【{index}】"
            f"⏰ {time_str}\n"
            f"👤 {item_author_label(item)}\n"
            f"📑 {dynamic_brief(item)}\n"
        )

    return (
        reply_text
        + "-------------------------\n"
        + "💡 两分钟内有效"
    )


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


@dynamic_menu_matcher.handle()
async def handle_dynamic_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    try:
        await send_event_reply(
            dynamic_menu_matcher,
            event,
            "🔄 正在拉取B站动态...",
        )

        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if is_bili_auth_invalid(response.status_code, res_json):
            await send_bili_login_qrcode_to_superusers(
                "用户查询动态时发现B站登录失效"
            )
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "⚠️ Cookie已失效。",
            )

        items = res_json.get("data", {}).get("items", [])
        if not items:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📥 没有动态数据。",
            )

        target_dynamics = find_target_dynamics(items)
        if not target_dynamics:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📥 近期没有公开动态。",
            )

        target_dynamics.sort(key=lambda value: value[0], reverse=True)
        menu_list = target_dynamics[:10]
        for pub_ts, item in menu_list:
            author_mid = item_author_mid(item)
            if author_mid:
                save_dynamic_history_item(
                    item,
                    pub_ts=pub_ts,
                    author_mid=author_mid,
                    author_name=item_author_name(item),
                    brief=dynamic_brief(item),
                )

        state[DYNAMIC_ITEMS_KEY] = [item for _, item in menu_list]

        logger.info(f"user {event.user_id} fetched Bilibili dynamic menu")
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DYNAMIC_CONVERSATION_NAMESPACE,
            handlers=[handle_dynamic_select],
            reply_check=_is_dynamic_select_reply,
            prompt=Message(_build_menu_text(menu_list)),
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


@update_dynamic_matcher.handle()
async def handle_update_dynamic(event: MessageEvent) -> None:
    if not is_bili_superuser(event.user_id):
        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "⛔ 仅超级管理员可用。",
        )

    try:
        logger.info(f"superuser {event.user_id} manually refreshed Bilibili")
        await send_event_reply(
            update_dynamic_matcher,
            event,
            "⚡ 正在刷新动态...",
        )

        did_run = await run_check_logic(is_startup_check=True)
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


async def handle_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    try:
        select_num = int(event.get_plaintext().strip())
        cached_items = state.get(DYNAMIC_ITEMS_KEY, [])
        if not cached_items:
            await finish_event_reply(
                matcher,
                event,
                "⏰ 会话已超时，请重新发送“动态”。",
            )

        if select_num < 1 or select_num > len(cached_items):
            await send_event_reply(
                matcher,
                event,
                f"请输入 1~{len(cached_items)} 之间的数字。",
            )
            await _wait_dynamic_select(matcher, event)

        target_item = cached_items[select_num - 1]
        final_message = parse_single_item(
            target_item,
            item_pub_ts(target_item),
            menu_mode=True,
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
