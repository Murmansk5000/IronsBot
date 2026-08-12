from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.dynamic_history import save_target_dynamics
from ironsbot.services.bilibili.hydration import (
    DynamicDetailFetcher,
    hydrate_dynamic_item,
)
from ironsbot.services.bilibili.menu import (
    DYNAMIC_MENU_DEFAULT_LIMIT,
    DynamicDetailSelection,
    DynamicMenuResult,
    build_dynamic_detail_for_selection,
    build_dynamic_menu_text,
    dynamic_record_ids,
)
from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_id,
    item_author_mid,
    target_dynamics_from_response,
)
from ironsbot.services.bilibili.push import build_dynamic_history_snapshot
from ironsbot.services.bilibili.schedule import AutoCheckState
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.core.tasks import TaskSpawner
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
    fetch_detail: DynamicDetailFetcher
    spawn: TaskSpawner
    external_references: SeerInfoReferences | None = None
    check_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    auto_check_state: AutoCheckState = field(default_factory=AutoCheckState)
    pending_check: bool = field(default=False, init=False)
    _detail_tasks: dict[str, asyncio.Task[dict[str, Any]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _delivery_tasks: dict[str, asyncio.Task[None]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _history_backfill_attempted: bool = field(default=False, init=False, repr=False)

    async def resolve_dynamic_item(
        self,
        item: dict[str, Any],
        *,
        cookie: str | None = None,
    ) -> dict[str, Any]:
        typed_item = dict(item)
        item_id = dynamic_id(typed_item)
        if not item_id or dynamic_content(typed_item):
            return typed_item

        task = self._detail_tasks.get(item_id)
        if task is None:
            task = self.spawn(
                hydrate_dynamic_item(
                    typed_item,
                    cookie=self.cookie_store.load() if cookie is None else cookie,
                    fetch_detail=self.fetch_detail,
                ),
                name=f"bilibili-dynamic-detail-{item_id}",
            )
            self._detail_tasks[item_id] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._detail_tasks.get(item_id) is task:
                self._detail_tasks.pop(item_id, None)

    def delivery_in_progress(self, item_id: str) -> bool:
        task = self._delivery_tasks.get(item_id)
        return task is not None and not task.done()

    def spawn_delivery(
        self,
        item_id: str,
        coroutine: Coroutine[Any, Any, None],
    ) -> asyncio.Task[None]:
        task = self.spawn(coroutine, name=f"bilibili-delivery-{item_id}")
        self._delivery_tasks[item_id] = task
        task.add_done_callback(
            lambda finished: self._remove_delivery_task(item_id, finished)
        )
        return task

    def _remove_delivery_task(
        self,
        item_id: str,
        task: asyncio.Task[None],
    ) -> None:
        if self._delivery_tasks.get(item_id) is task:
            self._delivery_tasks.pop(item_id, None)

    async def backfill_recent_empty_bodies(
        self,
        *,
        days: int = 7,
        limit: int = 20,
    ) -> int:
        """Update recent saved official dynamics without re-delivering them."""

        if self._history_backfill_attempted:
            return 0
        account = self.config.accounts.get(self.config.seer_categories.account)
        if not self.config.seer_categories.enabled or account is None:
            return 0

        cutoff = int(time.time()) - max(days, 0) * 24 * 60 * 60
        updated = 0
        cookie = self.cookie_store.load()
        if not cookie:
            return 0
        self._history_backfill_attempted = True
        for record in self.history.list(
            limit=self.config.storage.history_max_items,
            uid=account.uid,
        ):
            if record.pub_ts < cutoff or dynamic_content(record.item):
                continue
            if updated >= max(limit, 0):
                break
            resolved = await self.resolve_dynamic_item(record.item, cookie=cookie)
            if not dynamic_content(resolved):
                continue
            snapshot = build_dynamic_history_snapshot(
                resolved,
                pub_ts=record.pub_ts,
                author_mid=record.uid,
                suppression_reason=record.suppression_reason,
                pushed=record.pushed,
            )
            self.history.save_snapshot(snapshot)
            updated += 1
        if updated:
            logger.info("Bilibili dynamic history bodies backfilled: %s", updated)
        return updated

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
            cookie = self.cookie_store.load()
            target_dynamics = [
                (pub_ts, await self.resolve_dynamic_item(item, cookie=cookie))
                for pub_ts, item in target_dynamics
            ]
            official_dynamics = [
                (pub_ts, item)
                for pub_ts, item in target_dynamics
                if self.targets.is_seer_category_uid(item_author_mid(item))
            ]
            other_dynamics = [
                (pub_ts, item)
                for pub_ts, item in target_dynamics
                if not self.targets.is_seer_category_uid(item_author_mid(item))
            ]
            save_target_dynamics(
                self.history,
                other_dynamics,
                suppress_patterns=self.config.filters.suppress_push_patterns,
            )
            save_target_dynamics(
                self.history,
                official_dynamics,
                suppress_patterns=[],
            )

        records = self.history.list(
            limit=DYNAMIC_MENU_DEFAULT_LIMIT,
            uids=query_uids,
        )
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
            prompt=self.history_reference_message(build_dynamic_menu_text(records)),
        )

    def history_reference_message(self, message: str) -> str:
        if self.external_references is None:
            return message
        return self.external_references.append(
            message,
            SeerInfoReference.BILIBILI_HISTORY,
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
