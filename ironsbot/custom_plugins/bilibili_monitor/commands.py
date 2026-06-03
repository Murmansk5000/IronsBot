import time
from datetime import datetime
from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.rule import Rule

from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    finish_event_reply,
    normalize_command_text,
    send_event_reply,
)

from .auth import is_bili_auth_invalid, send_bili_login_qrcode_to_superusers
from .cache import get_saved_cookie
from .client import fetch_dynamic_feed
from .parser import (
    dynamic_brief,
    find_target_dynamics,
    item_author_label,
    item_pub_ts,
    parse_single_item,
)
from .permissions import (
    is_bili_superuser,
    is_dynamic_query_allowed,
    is_dynamic_update_allowed,
)
from .service import run_check_logic

DYNAMIC_CACHE_SESSION: dict[str, dict[str, Any]] = {}
DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
DYNAMIC_SELECT_COMMANDS = tuple(str(number) for number in range(1, 11))
DYNAMIC_MENU_TIMEOUT_SECONDS = 120


def _get_dynamic_session_key(event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return f"{event.user_id}_{group_id}"

    return f"{event.user_id}_private"


async def _has_dynamic_menu_session(event: MessageEvent) -> bool:
    if not is_dynamic_query_allowed(event):
        return False

    return _get_dynamic_session_key(event) in DYNAMIC_CACHE_SESSION


async def _is_dynamic_menu_command(event: MessageEvent) -> bool:
    if not is_dynamic_query_allowed(event):
        return False

    return command_text_matches(
        event.get_plaintext(),
        DYNAMIC_MENU_COMMANDS,
    )


async def _is_update_dynamic_command(event: MessageEvent) -> bool:
    if not command_text_matches(
        event.get_plaintext(),
        DYNAMIC_UPDATE_COMMANDS,
    ):
        return False

    return is_dynamic_update_allowed(event)


async def _is_dynamic_select_command(event: MessageEvent) -> bool:
    if not await _has_dynamic_menu_session(event):
        return False

    return normalize_command_text(event.get_plaintext()) in DYNAMIC_SELECT_COMMANDS


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

num_select_matcher = on_message(
    rule=Rule(_is_dynamic_select_command),
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
        time_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M:%S")
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


@dynamic_menu_matcher.handle()
async def handle_dynamic_menu(event: MessageEvent) -> None:
    session_key = _get_dynamic_session_key(event)

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

        DYNAMIC_CACHE_SESSION[session_key] = {
            "expire": time.time() + DYNAMIC_MENU_TIMEOUT_SECONDS,
            "items": [item for _, item in menu_list],
        }

        logger.info(f"user {event.user_id} fetched Bilibili dynamic menu")
        await finish_event_reply(
            dynamic_menu_matcher,
            event,
            Message(_build_menu_text(menu_list)),
        )

    except FinishedException:
        raise
    except Exception as e:
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
    except Exception as e:
        logger.error(f"manual Bilibili dynamic refresh failed: {e}")
        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "❌ 动态刷新失败。",
        )


@num_select_matcher.handle()
async def handle_dynamic_select(event: MessageEvent) -> None:
    session_key = _get_dynamic_session_key(event)
    session_data = DYNAMIC_CACHE_SESSION.get(session_key)
    if not session_data:
        return

    if time.time() > session_data["expire"]:
        del DYNAMIC_CACHE_SESSION[session_key]
        await finish_event_reply(
            num_select_matcher,
            event,
            "⏰ 会话已超时，请重新发送“动态”。",
        )

    try:
        select_num = int(event.get_plaintext().strip())
        cached_items = session_data["items"]
        if select_num < 1 or select_num > len(cached_items):
            return

        target_item = cached_items[select_num - 1]
        final_message = parse_single_item(
            target_item,
            item_pub_ts(target_item),
            menu_mode=True,
        )

        session_data["expire"] = time.time() + DYNAMIC_MENU_TIMEOUT_SECONDS
        if final_message:
            await finish_event_reply(
                num_select_matcher,
                event,
                Message(final_message),
            )

    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"Bilibili dynamic number select failed: {e}")
        await finish_event_reply(
            num_select_matcher,
            event,
            "❌ 动态详情解析失败。",
        )
