# SPDX-License-Identifier: MIT
import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.activity.commands import (
    is_current_seer_activity_text,
    is_soon_ending_seer_activity_text,
)
from ironsbot.services.activity.config import get_activity_config
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
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
SOON_ENDING_THRESHOLD = timedelta(days=7)
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)


async def _is_current_seer_activity_command(event: Event) -> bool:
    return is_current_seer_activity_text(event.get_plaintext())


async def _is_soon_ending_seer_activity_command(event: Event) -> bool:
    return is_soon_ending_seer_activity_text(event.get_plaintext())


_activity_info_cache = ActivityInfoCache()


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _activity_db_session_factory() -> Any:
    from ironsbot.integrations.db_registry import db_manager

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


async def handle_current_seer_activity(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        await asyncio.to_thread(build_current_activity_message),
    )


async def handle_soon_ending_seer_activity(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        await asyncio.to_thread(build_current_activity_message, soon_only=True),
    )


def install(registry: MatcherRegistry) -> None:
    current_matcher = registry.on_message(
        policy=CommandPolicy.command("seer_activity_current"),
        rule=Rule(_is_current_seer_activity_command) & no_reply(),
        permission=SUPERUSER,
        priority=get_matcher_priority("activity", 5),
        block=True,
    )
    current_matcher.append_handler(handle_current_seer_activity)

    ending_matcher = registry.on_message(
        policy=CommandPolicy.command("seer_activity_ending"),
        rule=(
            Rule(lambda event: is_event_feature_allowed(event, "seer_activity_query"))
            & Rule(_is_soon_ending_seer_activity_command)
            & no_reply()
        ),
        priority=get_matcher_priority("activity", 5),
        block=True,
    )
    ending_matcher.append_handler(handle_soon_ending_seer_activity)
