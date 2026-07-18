# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.services.bilibili.accounts import get_bili_config
from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.client import fetch_dynamic_feed
from ironsbot.services.bilibili.cookie_cache import get_saved_cookie
from ironsbot.services.bilibili.dynamic_history import (
    list_dynamic_history,
    save_target_dynamic_history,
)
from ironsbot.services.bilibili.menu import (
    DYNAMIC_IDS_STATE_KEY,
    build_dynamic_detail_for_selection,
    build_dynamic_menu_text,
    dynamic_record_ids,
)
from ironsbot.services.bilibili.parser import target_dynamics_from_response
from ironsbot.services.bilibili.targets import query_uids_for_event
from ironsbot.shared.messaging import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)

from .auth import send_bili_login_qrcode_to_superusers
from .command_rules import is_dynamic_select_reply

DYNAMIC_CONVERSATION_NAMESPACE = "bilibili_dynamic_menu"

async def wait_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=DYNAMIC_CONVERSATION_NAMESPACE,
        handlers=[handle_dynamic_select],
        reply_check=is_dynamic_select_reply,
    )

async def handle_dynamic_menu_action(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    try:
        query_uids = query_uids_for_event(event)
        logger.info(
            f"Bilibili dynamic menu query: user={event.user_id} uids={query_uids}"
        )
        if not query_uids:
            await finish_event_reply(
                matcher,
                event,
                "📭 当前会话没有配置可查询的 B 站账号。",
            )

        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if is_bili_auth_invalid(response.status_code, res_json):
            await send_bili_login_qrcode_to_superusers(
                "用户查询动态时发现 B 站登录失效"
            )
            await finish_event_reply(
                matcher,
                event,
                "⚠️ B 站 Cookie 已失效，请超级管理员重新登录。",
            )

        target_dynamics = target_dynamics_from_response(
            res_json,
            query_uids,
            newest_first=True,
        )
        if target_dynamics:
            save_target_dynamic_history(
                target_dynamics,
                suppress_patterns=get_bili_config().filters.suppress_push_patterns,
            )

        records = list_dynamic_history(limit=10, uids=query_uids)
        if not records:
            await finish_event_reply(
                matcher,
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
            reply_check=is_dynamic_select_reply,
            prompt=Message(build_dynamic_menu_text(records)),
        )

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili dynamic menu failed: {e}")
        await finish_event_reply(
            matcher,
            event,
            "❌ 获取动态列表失败。",
        )

async def handle_dynamic_select_action(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    try:
        cached_ids = state.get(DYNAMIC_IDS_STATE_KEY, [])
        selection = build_dynamic_detail_for_selection(
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
            await wait_dynamic_select(matcher, event)
            return

        if selection.status == "out_of_range":
            await send_event_reply(
                matcher,
                event,
                f"请输入 1~{selection.available_count} 之间的数字。",
            )
            await wait_dynamic_select(matcher, event)
            return

        if selection.status == "missing":
            await finish_event_reply(
                matcher,
                event,
                "❌ 没找到这条历史动态，请重新发送“动态”。",
            )

        if selection.status == "parse_failed":
            await finish_event_reply(
                matcher,
                event,
                "❌ 动态详情解析失败。",
            )

        if selection.message:
            await send_event_reply(
                matcher,
                event,
                selection.message,
            )

        await wait_dynamic_select(matcher, event)

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
    await handle_dynamic_select_action(matcher, event, state)
