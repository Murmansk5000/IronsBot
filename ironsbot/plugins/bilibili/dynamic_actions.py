# SPDX-License-Identifier: GPL-3.0-or-later

from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
)
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.runtime.conversations import enter_event_reply_conversation
from ironsbot.runtime.matchers import bind_async
from ironsbot.runtime.replies import (
    finish_event_reply,
    message_event_target,
    send_event_reply,
)
from ironsbot.services.bilibili.menu import DYNAMIC_IDS_STATE_KEY
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from ironsbot.services.bilibili.service import BilibiliService

from .command_rules import is_dynamic_select_reply
from .delivery import build_dynamic_message

DYNAMIC_CONVERSATION_NAMESPACE = "bilibili_dynamic_menu"


async def wait_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
    service: BilibiliService,
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=DYNAMIC_CONVERSATION_NAMESPACE,
        handlers=[bind_async(handle_dynamic_select_action, service=service)],
        reply_check=is_dynamic_select_reply,
    )

async def handle_dynamic_menu_action(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    service: BilibiliService,
    monitor: BilibiliMonitorService,
) -> None:
    try:
        target_type, target_id, _ = message_event_target(event)
        result = await service.query_dynamic_menu(
            target_type,
            target_id,
            event.user_id,
        )
        if result.status == "no_accounts":
            await finish_event_reply(
                matcher,
                event,
                "📭 当前会话没有配置可查询的 B 站账号。",
            )
        if result.status == "auth_invalid":
            await monitor.notify_auth_invalid("用户查询动态时发现 B 站登录失效")
            await finish_event_reply(
                matcher,
                event,
                "⚠️ B 站 Cookie 已失效，请超级管理员重新登录。",
            )
        if result.status == "no_history":
            await finish_event_reply(
                matcher,
                event,
                "📭 没有可展示的历史动态。",
            )

        state[DYNAMIC_IDS_STATE_KEY] = list(result.dynamic_ids)
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DYNAMIC_CONVERSATION_NAMESPACE,
            handlers=[bind_async(handle_dynamic_select_action, service=service)],
            reply_check=is_dynamic_select_reply,
            prompt=Message(result.prompt),
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
    service: BilibiliService,
) -> None:
    try:
        cached_ids = state.get(DYNAMIC_IDS_STATE_KEY, [])
        selection = service.select_dynamic(
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
            await wait_dynamic_select(matcher, event, service)
            return

        if selection.status == "out_of_range":
            await send_event_reply(
                matcher,
                event,
                f"请输入 1~{selection.available_count} 之间的数字。",
            )
            await wait_dynamic_select(matcher, event, service)
            return

        if selection.status == "missing":
            await finish_event_reply(
                matcher,
                event,
                "❌ 没找到这条历史动态，请重新发送“动态”。",
            )

        if selection.record is not None:
            message = build_dynamic_message(
                selection.record.item,
                selection.record.pub_ts,
                menu_mode=True,
            )
            if message is None:
                await finish_event_reply(
                    matcher,
                    event,
                    "❌ 动态详情解析失败。",
                )
                return
            await send_event_reply(
                matcher,
                event,
                message,
            )

        await wait_dynamic_select(matcher, event, service)

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili dynamic number select failed: {e}")
        await finish_event_reply(
            matcher,
            event,
            "❌ 动态详情解析失败。",
        )
