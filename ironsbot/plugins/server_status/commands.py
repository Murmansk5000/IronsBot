# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""Server status command services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ironsbot.shared.features.visibility import event_has_feature
from ironsbot.shared.messaging import finish_event_reply

from .notice import (
    _build_fetch_failed_reply,
    _build_no_notice_reply,
    _build_notice_reply,
    _build_open_reply,
    _now,
    fetch_server_notice_text,
)
from .status import HeadlessStatus, get_headless_status

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService

    from .broadcast import OpenBroadcast


async def handle_normal_status(
    matcher: Matcher,
    event: MessageEvent,
    broadcast: OpenBroadcast,
    headless: HeadlessService,
) -> None:
    if not event_has_feature(broadcast.features, event, "server_status_query"):
        logger.info(
            "normal server status command ignored: "
            "server_status_query feature not allowed"
        )
        return

    now = _now()
    headless_status = get_headless_status(headless)
    if headless_status.connected:
        await headless.mark_available(source="开服了吗")
    else:
        await headless.mark_unavailable(headless_status.reason, source="开服了吗")

    try:
        notice_text = await fetch_server_notice_text()
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning("开服公告读取失败")
        if headless_status.connected:
            await broadcast.send(event, now=now)
        await finish_event_reply(
            matcher,
            event,
            _build_fetch_failed_reply(now, e, headless_status=headless_status),
            mention_sender=True,
        )
        return

    if headless_status.connected:
        await broadcast.send(event, now=now)
        await finish_event_reply(
            matcher,
            event,
            _build_open_reply(now, notice_text=notice_text),
            mention_sender=True,
        )
        return

    if notice_text:
        await finish_event_reply(
            matcher,
            event,
            _build_notice_reply(notice_text),
            mention_sender=True,
        )
        return

    await finish_event_reply(
        matcher,
        event,
        _build_no_notice_reply(now, headless_status=headless_status),
        mention_sender=True,
    )

async def handle_admin_status(
    matcher: Matcher,
    event: MessageEvent,
    broadcast: OpenBroadcast,
    headless: HeadlessService,
) -> None:
    now = _now()
    lines = ["🛠【管理员开服查询】"]
    headless_status = get_headless_status(headless)
    if headless_status.connected:
        await headless.mark_available(source="/开服查询")
        lines.append("无头状态：已登录游戏服务器。")
    else:
        await headless.mark_unavailable(headless_status.reason, source="/开服查询")
        lines.append(f"无头状态：未登录（{headless_status.reason}）。")
        try:
            user_id = await headless.login()
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).warning("管理员开服查询触发无头重连失败")
            headless_status = HeadlessStatus(connected=False, reason=str(e))
            await headless.mark_unavailable(str(e), source="/开服查询重连")
            lines.append(f"重连结果：失败：{e}")
        else:
            headless_status = HeadlessStatus(connected=True)
            await headless.mark_available(
                source="/开服查询重连",
                user_id=user_id,
            )
            lines.append(f"重连结果：已登录米米号 {user_id}。")

    try:
        notice_text = await fetch_server_notice_text()
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning("管理员开服查询读取公告失败")
        if headless_status.connected:
            await broadcast.send(event, now=now)
        lines.extend(
            (
                "",
                _build_fetch_failed_reply(now, e, headless_status=headless_status),
            )
        )
    else:
        lines.append("")
        if headless_status.connected:
            await broadcast.send(event, now=now)
            lines.append(_build_open_reply(now, notice_text=notice_text))
        elif notice_text:
            lines.append(_build_notice_reply(notice_text))
        else:
            lines.append(
                _build_no_notice_reply(now, headless_status=headless_status)
            )

    await finish_event_reply(
        matcher,
        event,
        "\n".join(lines),
        mention_sender=True,
    )
