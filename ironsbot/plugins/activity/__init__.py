# SPDX-License-Identifier: MIT
import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import on_message, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.services.activity.commands import (
    is_current_seer_activity_text,
    is_soon_ending_seer_activity_text,
)
from ironsbot.services.activity.models import (
    ActivityInfoCache,
)
from ironsbot.services.activity.repository import load_activity_rows
from ironsbot.services.activity.seer_activity import (
    SeerActivitySource,
    build_seer_activity_message,
)
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .config import Config, get_activity_config

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
ACTIVITY_REMINDER_PLUGIN_NAME = "activity_reminder"
SOON_ENDING_THRESHOLD = timedelta(days=7)
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)


async def _is_current_seer_activity_command(event: Event) -> bool:
    return is_current_seer_activity_text(event.get_plaintext())


async def _is_soon_ending_seer_activity_command(event: Event) -> bool:
    return is_soon_ending_seer_activity_text(event.get_plaintext())


__plugin_meta__ = PluginMetadata(
    name="活动结束提醒",
    description="从 SeerAPI 活动数据读取结束时间，提前提醒活动即将结束",
    usage=(
        "【活动结束提醒】\n"
        "按 activity.lead_hours 配置提前提醒活动即将结束。\n"
        "Target groups use feature: seer_activity_push.\n"
        "Target users use feature: seer_activity_push.\n"
        "超级管理员可发 /当前活动、活动列表、活动时间 查看当前活动和剩余时间；"
        "发送 快结束活动 查看不足 7 天结束的活动。"
    ),
    config=Config,
)


_activity_info_cache = ActivityInfoCache()


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _activity_db_session_factory() -> Any:
    require("ironsbot.plugins.seer_data")
    from ironsbot.plugins.db_sync.manager import db_manager

    return db_manager.get_session


def _load_activity_rows() -> list[Mapping[str, Any]]:
    return load_activity_rows(
        _activity_db_session_factory(),
        database_name=SEERAPI_DB_NAME,
        only_shown=get_activity_config().only_shown,
    )


_seer_activity_source = SeerActivitySource(
    cache=_activity_info_cache,
    load_rows=_load_activity_rows,
    cache_ttl=ACTIVITY_INFO_CACHE_TTL,
    soon_ending_threshold=SOON_ENDING_THRESHOLD,
)


def build_current_activity_message(
    now: datetime | None = None,
    *,
    limit: int | None = None,
    soon_only: bool = False,
) -> str:
    current_time = now or _now()
    return build_seer_activity_message(
        _seer_activity_source,
        current_time,
        limit=limit,
        soon_only=soon_only,
    )


current_activity_matcher = on_message(
    rule=Rule(_is_current_seer_activity_command) & no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("activity", 5),
    block=True,
)

soon_ending_activity_matcher = on_message(
    rule=(
        Rule(lambda event: is_event_feature_allowed(event, "seer_activity_query"))
        & Rule(_is_soon_ending_seer_activity_command)
        & no_reply()
    ),
    priority=get_matcher_priority("activity", 5),
    block=True,
)


class ActivityReminderPlugin:
    name = ACTIVITY_REMINDER_PLUGIN_NAME
    feature = "seer_activity_query"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        from ironsbot.shared.messaging import finish_event_reply

        matcher = context.matcher or soon_ending_activity_matcher
        if context.action == "current":
            await finish_event_reply(
                matcher,
                event,
                await asyncio.to_thread(build_current_activity_message),
            )
            return

        if context.action == "soon_ending":
            await finish_event_reply(
                matcher,
                event,
                await asyncio.to_thread(build_current_activity_message, soon_only=True),
            )


register_plugin(ActivityReminderPlugin())


@current_activity_matcher.handle()
async def handle_current_seer_activity(
    event: MessageEvent,
) -> None:
    await dispatch_plugin(
        plugin_name=ACTIVITY_REMINDER_PLUGIN_NAME,
        event=event,
        matcher=current_activity_matcher,
        action="current",
    )


@soon_ending_activity_matcher.handle()
async def handle_soon_ending_seer_activity(event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=ACTIVITY_REMINDER_PLUGIN_NAME,
        event=event,
        matcher=soon_ending_activity_matcher,
        action="soon_ending",
    )
