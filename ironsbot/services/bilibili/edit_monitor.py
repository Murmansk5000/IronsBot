# SPDX-License-Identifier: MIT
"""Observe revisions before history replacement and project their durable outbox."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.time import TZ_CN

from .auth import is_bili_auth_invalid
from .categories import classify_dynamic
from .hydration import detail_item
from .parser import dynamic_suppression_reason, item_author_mid
from .push import build_dynamic_history_snapshot_for_item
from .revisions import complete_revision, delivery_key, revision_meta
from .schedule import current_interval_minutes

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .monitor import DynamicPushSender
    from .service import BilibiliService
    from .target_models import BiliPushTargets

_LOGGER = logging.getLogger(__name__)
HTTP_OK = 200


class RevisionStore(Protocol):
    def observe(
        self,
        item: dict[str, Any],
        pub_ts: int,
        uid: int,
        *,
        clock: float | None = None,
        baseline_only: bool = False,
    ) -> str | None: ...
    def pending(self, *, clock: float | None = None) -> list[dict[str, Any]]: ...
    def acknowledge(self, key: str) -> None: ...
    def due(
        self, excluded: set[str], *, clock: float | None = None
    ) -> list[tuple[str, int]]: ...
    def prune(self, *, clock: float | None = None) -> None: ...


@dataclass(slots=True)
class BiliEditMonitor:
    service: BilibiliService
    store: RevisionStore
    send: DynamicPushSender
    on_auth_invalid: Callable[[str], Awaitable[None]]
    clock: Callable[[], float] = time.time
    _last_review: float | None = None
    _flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        allowed = self.service.targets.monitored_uids()
        for record in self.service.history.list(
            limit=self.service.config.storage.history_max_items
        ):
            if record.uid in allowed:
                self.store.observe(
                    record.item,
                    record.pub_ts,
                    record.uid,
                    clock=self.clock(),
                    baseline_only=True,
                )

    def observe(self, item: dict[str, Any], pub_ts: int, uid: int) -> None:
        self.store.observe(item, pub_ts, uid, clock=self.clock())

    async def _deliver(
        self,
        item: dict[str, Any],
        published: int,
        uid: int,
        targets: BiliPushTargets,
        categories: tuple[str, ...],
    ) -> None:
        await self.send(item, published, uid, targets, categories)

    async def flush(self) -> None:
        async with self._flush_lock:
            for item in self.store.pending(clock=self.clock()):
                key, uid = delivery_key(item), item_author_mid(item)
                published = int(revision_meta(item)["published_at"])
                if (
                    uid not in self.service.targets.monitored_uids()
                    or dynamic_suppression_reason(
                        item, self.service.targets.suppress_patterns_for_uid(uid)
                    )
                ):
                    self.store.acknowledge(key)
                    continue
                categories = classify_dynamic(
                    item, self.service.targets.category_config_for_uid(uid)
                )
                targets = self.service.targets.push_targets_for_dynamic(
                    uid, categories=categories
                )
                if not targets.has_targets:
                    self.store.acknowledge(key)
                    continue
                if self.service.register_delivery is None:
                    continue
                self.service.register_delivery(
                    item, published, uid, targets, categories
                )
                if not self.service.delivery_in_progress(key):
                    self.service.spawn_delivery(
                        key, self._deliver(item, published, uid, targets, categories)
                    )
                self.store.acknowledge(key)

    async def tick(self, seen: set[str], *, review: bool) -> None:
        await self.flush()
        now = self.clock()
        interval = (
            current_interval_minutes(
                self.service.config.polling, datetime.fromtimestamp(now, TZ_CN)
            )
            * 60
        )
        if not review or (
            self._last_review is not None and now - self._last_review < interval
        ):
            return
        self._last_review = now
        semaphore = asyncio.Semaphore(2)
        auth_failed = False

        async def refresh(source_id: str, uid: int) -> None:
            nonlocal auth_failed
            async with semaphore:
                if auth_failed or uid not in self.service.targets.monitored_uids():
                    return
                try:
                    response = await self.service.fetch_detail(
                        self.service.cookie_store.load(), source_id
                    )
                    if is_bili_auth_invalid(response.status_code, response.data):
                        if not auth_failed:
                            auth_failed = True
                            await self.on_auth_invalid("B站动态编辑复查登录已失效")
                        return
                    item = detail_item(response)
                    if (
                        response.status_code != HTTP_OK
                        or not isinstance(response.data, dict)
                        or response.data.get("code") != 0
                        or item is None
                        or str(item.get("id_str")) != source_id
                        or item_author_mid(item) != uid
                        or not complete_revision(item)
                    ):
                        return
                    record = self.service.history.get(source_id)
                    if record is None:
                        return
                    self.observe(item, record.pub_ts, uid)
                    snapshot = build_dynamic_history_snapshot_for_item(
                        item,
                        pub_ts=record.pub_ts,
                        suppress_patterns=self.service.targets.suppress_patterns_for_uid(
                            uid
                        ),
                    )
                    if snapshot is not None:
                        self.service.history.save_snapshot(snapshot)
                    self.service.observe_live_preview(item)
                except Exception as error:  # noqa: BLE001 - preserve prior snapshot
                    _LOGGER.warning(
                        "Bilibili edit detail unavailable: id=%s error=%s",
                        source_id,
                        type(error).__name__,
                    )

        await asyncio.gather(
            *(refresh(key, uid) for key, uid in self.store.due(seen, clock=now))
        )
        await self.flush()
        self.store.prune(clock=now)
