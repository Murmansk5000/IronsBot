# SPDX-License-Identifier: MIT
"""One application-owned live monitor, sharing dynamics' polling opportunities."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.time import TZ_CN
from ironsbot.services.bilibili.live_models import (
    LiveAccount,
    LiveNotice,
    LiveObservation,
    LiveSchedule,
    LiveStateStore,
    LiveStatusUnavailableError,
)
from ironsbot.services.bilibili.live_preview import (
    live_subscription_key,
    parse_live_preview,
)
from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.bilibili.live_preview import LivePreview
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.delivery_tasks import StoredDelivery
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery

logger = logging.getLogger(__name__)
LIVE_SOURCE = "bilibili_live"
LIVE_CHECK_SECONDS = 60
LIVE_WINDOW_SECONDS = 600
LIVE_NOTICE_SECONDS = 1800
PRUNE_INTERVAL_SECONDS = 3600
OFFLINE_CONFIRMATIONS = 2


@dataclass(slots=True)
class BiliLiveMonitor:
    service: BilibiliService
    store: LiveStateStore
    fetch: Callable[[list[int]], Awaitable[dict[int, LiveObservation]]]
    delivery: ProactiveMessageDelivery
    clock: Callable[[], float] = time.time
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _bootstrapped: bool = False
    _pruned_at: float = 0

    def ingest(self, item: dict[str, Any]) -> None:
        preview = parse_live_preview(item)
        if preview is None or preview.uid not in self.service.targets.monitored_uids():
            return
        account = self.store.account(preview.uid)
        if preview.published_at < account.latest_preview_at:
            return
        fingerprint = hashlib.sha256(dynamic_content(item).encode()).hexdigest()
        if account.source_revisions.get(preview.source_id) == fingerprint:
            return
        notices = self._apply_preview(account, preview)
        if notices is None:
            return
        account.latest_preview_at = preview.published_at
        account.source_revisions[preview.source_id] = fingerprint
        account.source_revisions = dict(list(account.source_revisions.items())[-1000:])
        self.store.save(account, notices)

    def _apply_preview(
        self, account: LiveAccount, preview: LivePreview
    ) -> tuple[LiveNotice, ...] | None:
        active = [
            schedule
            for schedule in account.schedules
            if not schedule.ended
            and (
                schedule.starts_at >= self.clock() - LIVE_WINDOW_SECONDS
                or (schedule.start_created and account.status == 1)
            )
        ]
        notices: tuple[LiveNotice, ...] = ()
        if preview.cancelled:
            selected = [
                s
                for s in active
                if preview.starts_at is None or s.starts_at == preview.starts_at
            ]
            if len(selected) != 1:
                return None
            selected[0].ended = True
        elif preview.starts_at is not None:
            schedule = next(
                (s for s in active if s.starts_at == preview.starts_at), None
            )
            owned = [s for s in active if preview.source_id in s.sources]
            if schedule is None and (preview.rescheduled or owned):
                candidates = owned or active
                if len(candidates) > 1:
                    return None
                schedule = candidates[0] if candidates else None
            if schedule is not None and schedule.starts_at != preview.starts_at:
                notices = self._reschedule_before(schedule, preview.starts_at)
                schedule.starts_at = preview.starts_at
            if schedule is None:
                schedule = LiveSchedule(
                    f"{preview.uid}:{int(preview.starts_at)}",
                    preview.starts_at,
                    preview.published_at,
                )
                account.schedules.append(schedule)
            if preview.source_id not in schedule.sources:
                schedule.sources.append(preview.source_id)
            schedule.published_at = preview.published_at
        else:
            return None
        return notices

    def _reschedule_before(
        self, schedule: LiveSchedule, starts_at: float
    ) -> tuple[LiveNotice, ...]:
        old = (
            self.store.notice(schedule.before_notice_key)
            if schedule.before_notice_key
            else None
        )
        outbox = self.delivery.outbox
        if old is None or outbox is None:
            return ()
        targets = []
        # Only an atomic skip of a pending unit proves it can safely be re-planned.
        for target in old.targets:
            task_id = hashlib.sha256(f"{old.key}:{target}:0".encode()).hexdigest()
            outbox.skip(task_id, "live_preview_rescheduled")
            if outbox.result(task_id).error_code == "live_preview_rescheduled":
                targets.append(target)
        if not targets:
            return ()
        key = f"{old.key}:rescheduled:{int(starts_at)}"
        schedule.before_notice_key = key
        scheduled = datetime.fromtimestamp(starts_at, TZ_CN).strftime("%Y-%m-%d %H:%M")
        return (
            replace(
                old,
                key=key,
                created_at=starts_at - LIVE_WINDOW_SECONDS,
                expires_at=starts_at,
                targets=tuple(targets),
                text=re.sub(
                    r"预计开播：[^\n]+", f"预计开播：{scheduled}（北京时间）", old.text
                ),
            ),
        )

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        records = self.service.history.list(
            limit=self.service.config.storage.history_max_items
        )
        for record in sorted(records, key=lambda record: record.pub_ts):
            self.ingest(record.item)
        self._bootstrapped = True

    async def tick(self, *, shared_due: bool = False, startup: bool = False) -> None:
        async with self._lock:
            first = not self._bootstrapped
            self._bootstrap()
            now = self.clock()
            selected = []
            for uid in self.service.targets.monitored_uids():
                if not self.service.targets.live_targets(uid):
                    continue
                account = self.store.account(uid)
                active = account.status == 1 or any(
                    not s.ended
                    and not s.start_created
                    and s.starts_at - 600 <= now <= s.starts_at + 600
                    for s in account.schedules
                )
                regular = shared_due and not startup
                due = (
                    first
                    or (active and now - account.checked_at >= LIVE_CHECK_SECONDS)
                    or (regular and now - account.checked_at >= 1)
                )
                if due and now >= account.retry_after:
                    selected.append(uid)
            await self._refresh(selected, now)
            await self._dispatch(now)
            if now - self._pruned_at >= PRUNE_INTERVAL_SECONDS:
                self.store.prune(now)
                self._pruned_at = now

    async def _refresh(self, uids: list[int], now: float) -> bool:
        success = True
        for index in range(0, len(uids), 20):
            batch = uids[index : index + 20]
            try:
                observations = await asyncio.wait_for(self.fetch(batch), timeout=12)
            except (LiveStatusUnavailableError, TimeoutError) as error:
                logger.warning(
                    "Bilibili live observation failed: kind=%s accounts=%d",
                    type(error).__name__,
                    len(batch),
                )
                observations = {}
            for uid in batch:
                account = self.store.account(uid)
                observation = observations.get(uid)
                if observation is None:
                    account.failures += 1
                    account.retry_after = now + min(
                        300, 60 * 2 ** min(account.failures - 1, 3)
                    )
                    self.store.save(account)
                    success = False
                    continue
                self._observe(account, observation, now)
        return success

    def _observe(
        self, account: LiveAccount, observation: LiveObservation, now: float
    ) -> None:
        previous = account.status
        account.room_id = observation.room_id
        account.checked_at = now
        account.observed_live = observation.live
        account.failures = 0
        account.retry_after = 0
        notices: list[LiveNotice] = []
        if observation.live:
            account.offline_count = 0
            if previous != 1:
                notices.extend(self._started(account, observation, now))
            account.status = 1
        elif previous == 1:
            account.offline_count += 1
            if account.offline_count >= OFFLINE_CONFIRMATIONS:
                account.status = 0
                for schedule in account.schedules:
                    if schedule.start_created:
                        schedule.ended = True
        else:
            account.status = 0
            account.offline_count = 0
        if not observation.live and account.status == 0:
            notices.extend(self._before(account, observation, now))
        account.schedules = [
            s for s in account.schedules if s.starts_at >= now - 30 * 86400
        ]
        self.store.save(account, tuple(notices))

    def _started(
        self, account: LiveAccount, observation: LiveObservation, now: float
    ) -> list[LiveNotice]:
        session = f"{account.uid}:{observation.live_time or int(now)}"
        previous_session = account.session
        account.session = session
        account.live_time = observation.live_time
        if account.status is None or previous_session == session:
            return []
        schedules = [
            s
            for s in account.schedules
            if not s.ended
            and s.starts_at - LIVE_WINDOW_SECONDS
            <= now
            <= s.starts_at + LIVE_WINDOW_SECONDS
        ]
        schedule = schedules[0] if len(schedules) == 1 else None
        if schedule and schedule.start_created:
            return []
        if schedule:
            schedule.start_created = True
        expires = (
            min(now + LIVE_NOTICE_SECONDS, observation.live_time + LIVE_NOTICE_SECONDS)
            if observation.live_time > 0
            else now + LIVE_NOTICE_SECONDS
        )
        if expires <= now:
            return []
        return [
            self._notice(
                account,
                "started",
                schedule.key if schedule else "",
                session,
                now,
                expires,
                f"【B站开播提醒】{observation.name}\n{observation.title}\n"
                f"已确认开播\nhttps://live.bilibili.com/{observation.room_id}",
            )
        ]

    def _before(
        self, account: LiveAccount, observation: LiveObservation, now: float
    ) -> list[LiveNotice]:
        notices = []
        for schedule in account.schedules:
            if schedule.ended or schedule.before_created or schedule.start_created:
                continue
            if schedule.starts_at - LIVE_WINDOW_SECONDS <= now < schedule.starts_at:
                scheduled = datetime.fromtimestamp(schedule.starts_at, TZ_CN).strftime(
                    "%Y-%m-%d %H:%M"
                )
                notices.append(
                    self._notice(
                        account,
                        "before",
                        schedule.key,
                        "",
                        now,
                        schedule.starts_at,
                        f"【B站直播预提醒】{observation.name}\n预计开播：{scheduled}（北京时间）\n"
                        f"以实际开播为准\nhttps://live.bilibili.com/{observation.room_id}",
                    )
                )
                schedule.before_created = True
                schedule.before_notice_key = notices[-1].key
        return notices

    def _notice(  # noqa: PLR0913 - explicit durable notice identity and expiry
        self,
        account: LiveAccount,
        kind: str,
        schedule: str,
        session: str,
        now: float,
        expires: float,
        text: str,
    ) -> LiveNotice:
        key = f"live:{account.uid}:{schedule or session}:{kind}"
        return LiveNotice(
            key,
            account.uid,
            kind,
            schedule,
            session,
            now,
            expires,
            text,
            tuple(self.service.targets.live_targets(account.uid)),
        )

    def _valid(self, notice: LiveNotice, account: LiveAccount, now: float) -> bool:
        if now >= notice.expires_at:
            return False
        schedule = next(
            (s for s in account.schedules if s.key == notice.schedule), None
        )
        if notice.kind == "before":
            return bool(
                schedule
                and not schedule.ended
                and not schedule.start_created
                and account.status == 0
                and now < schedule.starts_at
                and notice.expires_at == schedule.starts_at
            )
        return account.status == 1 and account.session == notice.session

    async def ready(self, task: StoredDelivery) -> bool | None:
        if task.intent.source_platform != LIVE_SOURCE:
            return True
        async with self._lock:
            notice = self.store.notice(task.intent.source_id)
            if notice is None or not self.service.targets.live_enabled(
                task.conversation, notice.uid
            ):
                return False
            now = self.clock()
            account = self.store.account(notice.uid)
            if now >= notice.expires_at:
                return False
            if now - account.checked_at >= LIVE_CHECK_SECONDS:
                if now < account.retry_after or not await self._refresh(
                    [notice.uid], now
                ):
                    return None
                account = self.store.account(notice.uid)
            if account.status == 1 and account.observed_live is False:
                return None
            return self._valid(notice, account, now)

    async def _dispatch(self, now: float) -> None:
        for notice in self.store.notices(now):
            account = self.store.account(notice.uid)
            if (
                now - account.checked_at >= LIVE_CHECK_SECONDS
                or now < account.retry_after
            ):
                continue
            targets = [
                target
                for target in notice.targets
                if self.service.targets.live_enabled(target, notice.uid)
            ]
            if self._valid(notice, account, now) and targets:
                await self.delivery.send(
                    OutboundMessage.from_text(notice.text),
                    targets,
                    action_name="Bilibili live reminder",
                    subscription_key=live_subscription_key(notice.uid),
                    intent=DeliveryIntent(
                        notice.key,
                        notice.expires_at,
                        feature="bili_push",
                        source_platform=LIVE_SOURCE,
                        source_id=notice.key,
                    ),
                )
            self.store.complete(notice.key)
