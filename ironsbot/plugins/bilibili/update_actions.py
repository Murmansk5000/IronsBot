# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher

from ironsbot.services.bilibili.resources import BilibiliResources
from ironsbot.shared.messaging import finish_event_reply, send_event_reply

from .service import run_check_logic


async def handle_update_dynamic_action(
    matcher: Matcher,
    event: MessageEvent,
    resources: BilibiliResources,
) -> None:
    if not resources.admin_notices.features.is_superuser(event.user_id):
        await finish_event_reply(
            matcher,
            event,
            "❌ 仅超级管理员可用。",
        )

    try:
        logger.info(f"superuser {event.user_id} manually refreshed Bilibili")
        await send_event_reply(
            matcher,
            event,
            "⚡ 正在刷新动态...",
        )

        did_run = await run_check_logic(
            resources,
            is_startup_check=True,
            force=True,
        )
        if not did_run:
            await finish_event_reply(
                matcher,
                event,
                "⏳ 动态刷新正在进行中，请稍后再试。",
            )

        await finish_event_reply(
            matcher,
            event,
            "✅ 动态刷新完成。",
        )

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"manual Bilibili dynamic refresh failed: {e}")
        await finish_event_reply(
            matcher,
            event,
            "❌ 动态刷新失败。",
        )
