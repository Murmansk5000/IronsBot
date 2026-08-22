# SPDX-License-Identifier: MIT
"""Opt-in topic publishing through the application's existing delivery pipeline."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol

from ironsbot.core.platform import ActorRef, ConversationRef
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.messaging.topic_models import (
    PushTopic,
    TopicDeliveryRecord,
    TopicDeliveryStatus,
    topic_subscription_key,
)
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.operations.scheduler import Scheduler

_LOGGER = logging.getLogger(__name__)


class PushTopicStore(Protocol):
    def topics(self) -> tuple[PushTopic, ...]: ...
    def create(self, topic: PushTopic) -> None: ...
    def set_enabled(self, key: str, *, enabled: bool) -> None: ...
    def delete(self, key: str) -> None: ...
    def subscribe(self, key: str, target: ConversationRef) -> None: ...
    def subscribers(self, key: str) -> tuple[ConversationRef, ...]: ...
    def claim(
        self, key: str, target: ConversationRef, dedup_key: str | None, now: float
    ) -> int | None: ...
    def finish(self, record_id: int, status: TopicDeliveryStatus) -> None: ...
    def prune(self, key: str, now: float) -> None: ...
    def history(self, key: str) -> tuple[TopicDeliveryRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class TopicPublication:
    message: OutboundMessage
    dedup_key: str | None = None


@dataclass(frozen=True, slots=True)
class TopicSchedule:
    id: str
    trigger: Literal["interval", "cron", "date"]
    provider: Callable[[], Awaitable[TopicPublication | None]]
    options: Mapping[str, str | int | float | datetime]


class PushTopicService:
    def __init__(
        self,
        store: PushTopicStore,
        delivery: ProactiveMessageDelivery,
        subscriptions: PushSubscriptionRepository,
        features: FeatureService,
        *,
        resolve_target: Callable[[str, ConversationRef], tuple[ConversationRef, ...]]
        | None = None,
    ) -> None:
        self.store = store
        self.delivery = delivery
        self.subscriptions = subscriptions
        self.features = features
        self.resolve_target = resolve_target
        self._schedules: dict[tuple[str, str], TopicSchedule] = {}
        self._scheduler: Scheduler | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self.known_keys: set[str] = set()

    def topic(self, key: str) -> PushTopic:
        topic = next((topic for topic in self.store.topics() if topic.key == key), None)
        if topic is None:
            raise ValueError("未找到该推送主题。")
        return topic

    def create(self, key: str, name: str, *, code_registered: bool = False) -> None:
        if not re.fullmatch(r"[\w-]{1,48}", key) or not name.strip():
            msg = "主题标识需为 1 至 48 个汉字、字母、数字、下划线或短横线。"
            raise ValueError(msg)
        if any(topic.key == key for topic in self.store.topics()):
            raise ValueError("该推送主题已经存在。")
        self.store.create(PushTopic(key, name.strip(), code_registered=code_registered))
        self.known_keys.add(key)

    async def register(
        self, key: str, name: str, schedules: tuple[TopicSchedule, ...] = ()
    ) -> None:
        """Register code-owned providers; invoke on every application startup."""
        existing = next(
            (
                topic
                for topic in await asyncio.to_thread(self.store.topics)
                if topic.key == key
            ),
            None,
        )
        if existing is None:
            await asyncio.to_thread(self.create, key, name, code_registered=True)
        elif not existing.code_registered:
            raise ValueError("主题已由用户创建，不能被程序注册覆盖。")
        for schedule in schedules:
            if not re.fullmatch(r"[\w-]{1,48}", schedule.id):
                msg = "invalid topic schedule id"
                raise ValueError(msg)
            if schedule.trigger == "date":
                run_date = schedule.options.get("run_date")
                if not isinstance(run_date, datetime) or run_date.tzinfo is None:
                    msg = "date schedules require an aware run_date"
                    raise ValueError(msg)
            self._schedules[key, schedule.id] = schedule
        self.known_keys.add(key)
        self._refresh_jobs(key, enabled=existing.enabled if existing else True)

    async def set_enabled(self, key: str, *, enabled: bool) -> None:
        await asyncio.to_thread(self.topic, key)
        await asyncio.to_thread(self.store.set_enabled, key, enabled=enabled)
        self._refresh_jobs(key, enabled=enabled)

    async def delete(self, key: str) -> None:
        if (await asyncio.to_thread(self.topic, key)).code_registered:
            raise ValueError("程序注册的主题不能通过口令删除。")
        self._remove_jobs(key)
        await asyncio.to_thread(self.store.delete, key)
        self.known_keys.discard(key)
        self._schedules = {
            pair: value for pair, value in self._schedules.items() if pair[0] != key
        }

    def subscribe(self, key: str, target: ConversationRef, *, enabled: bool) -> None:
        self.topic(key)
        if enabled:
            self.store.subscribe(key, target)
            self.subscriptions.restore(target, topic_subscription_key(key))
        else:
            self.subscriptions.unsubscribe(
                target, topic_subscription_key(key), "push_topics"
            )

    def subscription_options(
        self, target: ConversationRef
    ) -> list[PushSubscriptionOption]:
        if not self.allowed_target(target):
            return []
        return [
            PushSubscriptionOption(
                topic_subscription_key(topic.key),
                f"主题：{topic.name}",
                "push_topics",
                self.subscriptions.is_unsubscribed(
                    target, topic_subscription_key(topic.key)
                ),
            )
            for topic in self.store.topics()
            if target in self.store.subscribers(topic.key)
        ]

    def allowed_target(self, target: ConversationRef) -> bool:
        if self.features.conversation_has_feature(target, "blacklist"):
            return False
        if target.kind == "private":
            actor = ActorRef(target.platform, target.id)
            return self.features.is_feature_allowed(actor, target, "push_topics")
        return target.kind == "group" and self.features.conversation_has_feature(
            target,
            "push_topics",
        )

    async def publish(
        self,
        key: str,
        publication: TopicPublication,
        *,
        targets: tuple[ConversationRef, ...] | None = None,
    ) -> dict[str, int]:
        async with self._locks.setdefault(key, asyncio.Lock()):
            if not (await asyncio.to_thread(self.topic, key)).enabled:
                raise ValueError("该推送主题已停用。")
            destinations = (
                targets
                if targets is not None
                else await asyncio.to_thread(
                    self.store.subscribers,
                    key,
                )
            )
            counts: dict[str, int] = {}
            selected: set[ConversationRef] = set()
            for source in dict.fromkeys(destinations):
                # Recheck between sends so disabling stops an in-progress batch.
                if (
                    key not in self.known_keys
                    or not (await asyncio.to_thread(self.topic, key)).enabled
                ):
                    break
                target = await self._selected_target(key, source)
                if target is None or target in selected:
                    continue
                selected.add(target)
                now = time.time()
                claim = await asyncio.to_thread(
                    self.store.claim,
                    key,
                    target,
                    publication.dedup_key,
                    now,
                )
                if claim is None:
                    counts["duplicate"] = counts.get("duplicate", 0) + 1
                    continue
                status = await self._send_claimed(key, target, publication, claim)
                counts[status] = counts.get(status, 0) + 1
            await asyncio.to_thread(self.store.prune, key, time.time())
            return counts

    async def _selected_target(
        self,
        key: str,
        source: ConversationRef,
    ) -> ConversationRef | None:
        if not self.allowed_target(source) or await asyncio.to_thread(
            self.subscriptions.is_unsubscribed,
            source,
            topic_subscription_key(key),
        ):
            return None
        return source

    async def _send_claimed(
        self,
        key: str,
        target: ConversationRef,
        publication: TopicPublication,
        claim: int,
    ) -> TopicDeliveryStatus:
        status: TopicDeliveryStatus = "uncertain"
        try:
            summary = await self.delivery.send(
                publication.message,
                (target,),
                action_name=f"push_topic:{key}",
                subscription_key=topic_subscription_key(key),
            )
            if summary.succeeded:
                status = "delivered"
            elif summary.failed:
                # This historical delivery contract does not expose receipts.
                # Retain the claim until a definite delivery outcome is known.
                status = "uncertain"
            else:
                status = "skipped"
        except Exception:
            _LOGGER.exception("topic delivery failed before a definite result")
        finally:
            await asyncio.shield(asyncio.to_thread(self.store.finish, claim, status))
        return status

    async def start(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler
        self.stop_jobs()
        for topic in await asyncio.to_thread(self.store.topics):
            self.known_keys.add(topic.key)
            self._refresh_jobs(topic.key, enabled=topic.enabled)

    async def stop(self) -> None:
        self.stop_jobs()
        self._scheduler = None

    def stop_jobs(self) -> None:
        if self._scheduler is not None:
            JobRegistry(self._scheduler, "push_topic:").remove_by_prefix()

    def _remove_jobs(self, key: str) -> None:
        if self._scheduler is not None:
            JobRegistry(self._scheduler, f"push_topic:{key}:").remove_by_prefix()

    def _refresh_jobs(self, key: str, *, enabled: bool) -> None:
        if self._scheduler is None:
            return
        self._remove_jobs(key)
        if not enabled:
            return
        for (topic_key, schedule_id), schedule in self._schedules.items():
            if topic_key != key:
                continue
            run_date = schedule.options.get("run_date")
            if (
                schedule.trigger == "date"
                and isinstance(run_date, datetime)
                and run_date <= datetime.now(timezone.utc)
            ):
                continue
            self._scheduler.add_job(
                partial(self._run_schedule, key, schedule),
                schedule.trigger,
                id=f"push_topic:{key}:{schedule_id}",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=1,
                **dict(schedule.options),
            )

    async def _run_schedule(self, key: str, schedule: TopicSchedule) -> None:
        if not (await asyncio.to_thread(self.topic, key)).enabled:
            return
        publication = await schedule.provider()
        if publication is not None:
            await self.publish(key, publication)
