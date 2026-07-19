from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.dynamic_history import save_target_dynamics
from ironsbot.services.bilibili.menu import (
    DynamicDetailSelection,
    DynamicMenuResult,
    build_dynamic_detail_for_selection,
    build_dynamic_menu_text,
    dynamic_record_ids,
)
from ironsbot.services.bilibili.parser import target_dynamics_from_response
from ironsbot.services.bilibili.schedule import AutoCheckState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.services.bilibili.dynamic_history import BiliDynamicHistoryStore
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.messaging.subscriptions import PushTargetType

logger = logging.getLogger(__name__)


class BiliCookieStore(Protocol):
    def load(self) -> str: ...

    def save(self, cookie: str) -> None: ...


@dataclass(frozen=True, slots=True)
class BiliFeedResponse:
    status_code: int
    data: object


@dataclass(slots=True)
class BilibiliService:
    config: BiliConfig
    targets: BiliTargetService
    cookie_store: BiliCookieStore
    history: BiliDynamicHistoryStore
    fetch_feed: Callable[[str], Awaitable[BiliFeedResponse]]
    check_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    auto_check_state: AutoCheckState = field(default_factory=AutoCheckState)

    async def query_dynamic_menu(
        self,
        target_type: PushTargetType,
        target_id: int,
        user_id: int,
    ) -> DynamicMenuResult:
        query_uids = (
            self.targets.query_uids_for_group(user_id, target_id)
            if target_type == "group"
            else self.targets.query_uids_for_private(user_id)
        )
        logger.info(
            "Bilibili dynamic menu query: user=%s uids=%s",
            user_id,
            query_uids,
        )
        if not query_uids:
            return DynamicMenuResult(status="no_accounts")

        feed = await self.fetch_feed(self.cookie_store.load())
        if is_bili_auth_invalid(feed.status_code, feed.data):
            return DynamicMenuResult(status="auth_invalid")

        target_dynamics = target_dynamics_from_response(
            feed.data,
            query_uids,
            newest_first=True,
        )
        if target_dynamics:
            save_target_dynamics(
                self.history,
                target_dynamics,
                suppress_patterns=self.config.filters.suppress_push_patterns,
            )

        records = self.history.list(limit=10, uids=query_uids)
        if not records:
            return DynamicMenuResult(status="no_history")

        logger.info(
            "user %s fetched Bilibili dynamic menu for %s",
            user_id,
            query_uids,
        )
        return DynamicMenuResult(
            status="ok",
            dynamic_ids=tuple(dynamic_record_ids(records)),
            prompt=build_dynamic_menu_text(records),
        )

    def select_dynamic(
        self,
        cached_ids: list[object],
        raw_text: str,
    ) -> DynamicDetailSelection:
        return build_dynamic_detail_for_selection(
            self.history,
            cached_ids,
            raw_text,
        )
