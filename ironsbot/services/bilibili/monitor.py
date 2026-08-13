import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ironsbot.core.bilibili import SeerDynamicCategory
from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.checkpoints import (
    DynamicItem,
    initialize_missing_checkpoints,
    mark_checkpoint,
)
from ironsbot.services.bilibili.parser import (
    dynamic_id,
    item_author_mid,
    target_dynamics_from_response,
)
from ironsbot.services.bilibili.push import (
    DynamicHistorySnapshot,
    build_dynamic_history_snapshot_for_item,
    decide_dynamic_push_after_targets,
    decide_dynamic_push_before_targets,
    mark_history_snapshot_pushed,
)
from ironsbot.services.bilibili.schedule import (
    auto_check_due,
    boost_slots_at,
    boost_slots_due,
    mark_auto_check,
    mark_boost_slots_completed,
)
from ironsbot.services.bilibili.service import (
    BilibiliService,
    BiliFeedResponse,
)
from ironsbot.services.bilibili.targets import BiliPushTargets

logger = logging.getLogger(__name__)
HTTP_OK = 200
AuthInvalidHandler = Callable[[str], Awaitable[None]]
DynamicPushSender = Callable[
    [dict[str, Any], int, int, BiliPushTargets, tuple[SeerDynamicCategory, ...]],
    Awaitable[None],
]

@dataclass(frozen=True, slots=True)
class DynamicPushBatch:
    checkpoint_changed: bool
    discovered_new: bool = False
    delivery_tasks: tuple[asyncio.Task[None], ...] = ()


@dataclass(frozen=True, slots=True)
class MonitorCheckResult:
    executed: bool = False
    valid_response: bool = False
    discovered_new: bool = False

    def __bool__(self) -> bool:
        return self.executed


@dataclass(frozen=True, slots=True)
class ClaimedDynamicDelivery:
    item: dict[str, Any]
    pub_ts: int
    author_mid: int
    targets: BiliPushTargets
    categories: tuple[SeerDynamicCategory, ...]
    snapshot: DynamicHistorySnapshot
    history_id: str


async def _deliver_claimed_dynamic(
    service: BilibiliService,
    send_push: DynamicPushSender,
    delivery: ClaimedDynamicDelivery,
) -> None:
    started_at = time.monotonic()
    try:
        await send_push(
            delivery.item,
            delivery.pub_ts,
            delivery.author_mid,
            delivery.targets,
            delivery.categories,
        )
    except BaseException:
        service.history.release_delivery_claim(delivery.history_id)
        raise
    service.history.save_snapshot(mark_history_snapshot_pushed(delivery.snapshot))
    service.history.advance_checkpoint(delivery.author_mid, delivery.pub_ts)
    logger.info(
        "Bilibili dynamic delivery completed: dynamic=%s author=%s elapsed=%.3fs",
        delivery.history_id,
        delivery.author_mid,
        time.monotonic() - started_at,
    )


async def _is_valid_dynamic_response(
    feed: BiliFeedResponse,
    on_auth_invalid: AuthInvalidHandler,
) -> bool:
    if is_bili_auth_invalid(feed.status_code, feed.data):
        await on_auth_invalid("自动检查动态时发现 B 站登录失效")
        return False

    if feed.status_code != HTTP_OK:
        logger.warning(
            "Bilibili dynamic API returned HTTP %s",
            feed.status_code,
        )
        return False

    api_code = feed.data.get("code") if isinstance(feed.data, dict) else None
    if api_code != 0:
        logger.warning("Bilibili dynamic API returned code %s", api_code)
        return False
    return True


def _log_non_delivery_decision(
    status: str,
    snapshot: DynamicHistorySnapshot,
) -> None:
    if status == "suppressed":
        logger.info(
            "Bilibili dynamic push suppressed for "
            f"{snapshot.author_name} ({snapshot.author_mid}): "
            f"{snapshot.suppression_reason}"
        )
        return

    logger.info(
        "Bilibili dynamic saved without push target for "
        f"{snapshot.author_name} ({snapshot.author_mid})"
    )


async def _push_new_dynamics(
    service: BilibiliService,
    valid_dynamics: list[DynamicItem],
    checkpoints: dict[int, int],
    send_push: DynamicPushSender,
    *,
    cookie: str = "",
) -> DynamicPushBatch:
    checkpoint_changed = False
    discovered_new = False
    delivery_tasks: list[asyncio.Task[None]] = []
    for pub_ts, feed_item in valid_dynamics:
        item = await service.resolve_dynamic_item(feed_item, cookie=cookie)
        author_mid = item_author_mid(item)
        category_managed = service.targets.is_seer_category_uid(author_mid)
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=(
                []
                if category_managed
                else service.config.filters.suppress_push_patterns
            ),
        )
        if snapshot is None:
            continue

        author_mid = snapshot.author_mid
        categories = service.targets.classify_dynamic(
            author_mid,
            item,
            pub_ts,
        )
        last_saved_time = checkpoints.get(author_mid, 0)
        service.history.save_snapshot(snapshot)
        history_id = dynamic_id(item) or f"{author_mid}:{pub_ts}"
        previous = service.history.get(history_id)
        if previous is not None and previous.pushed:
            logger.info(
                "Bilibili dynamic already marked pushed; restoring checkpoint for "
                "%s (%s): %s",
                snapshot.author_name,
                author_mid,
                history_id,
            )
            checkpoint_changed = (
                mark_checkpoint(checkpoints, author_mid, pub_ts) or checkpoint_changed
            )
            continue

        targets: BiliPushTargets | None = None
        decision = decide_dynamic_push_before_targets(
            pub_ts=pub_ts,
            last_saved_time=last_saved_time,
            suppression_reason=snapshot.suppression_reason,
        )
        if decision is None:
            targets = service.targets.push_targets_for_uid(
                author_mid,
                categories=categories,
            )
            decision = decide_dynamic_push_after_targets(
                has_targets=targets.has_targets
            )

        if decision.status == "skip_existing":
            continue

        discovered_new = True

        if decision.status in {"suppressed", "no_targets"}:
            _log_non_delivery_decision(decision.status, snapshot)
            service.history.save_snapshot(mark_history_snapshot_pushed(snapshot))
            checkpoint_changed = (
                mark_checkpoint(checkpoints, author_mid, pub_ts) or checkpoint_changed
            )
            continue

        if targets is None:
            targets = service.targets.push_targets_for_uid(
                author_mid,
                categories=categories,
            )

        if service.delivery_in_progress(history_id):
            logger.info(
                "Bilibili dynamic delivery remains active; skipping %s (%s): %s",
                snapshot.author_name,
                author_mid,
                history_id,
            )
            continue
        if not service.history.try_claim_delivery(history_id):
            logger.info(
                "Bilibili dynamic delivery is already claimed; skipping %s (%s): %s",
                snapshot.author_name,
                author_mid,
                history_id,
            )
            continue

        delivery_tasks.append(
            service.spawn_delivery(
                history_id,
                _deliver_claimed_dynamic(
                    service,
                    send_push,
                    ClaimedDynamicDelivery(
                        item,
                        pub_ts,
                        author_mid,
                        targets,
                        categories,
                        snapshot,
                        history_id,
                    ),
                ),
            )
        )

    return DynamicPushBatch(
        checkpoint_changed,
        discovered_new,
        tuple(delivery_tasks),
    )


async def _do_check_logic(
    service: BilibiliService,
    on_auth_invalid: AuthInvalidHandler,
    send_push: DynamicPushSender,
) -> MonitorCheckResult:
    result = MonitorCheckResult(executed=True)
    try:
        cookie = service.cookie_store.load()
        feed = await service.fetch_feed(cookie)
        if not await _is_valid_dynamic_response(
            feed,
            on_auth_invalid,
        ):
            return result

        result = MonitorCheckResult(executed=True, valid_response=True)

        valid_dynamics = target_dynamics_from_response(
            feed.data,
            service.targets.monitored_uids(),
        )
        if not valid_dynamics:
            return result

        checkpoints = service.history.get_checkpoints()
        initialized_checkpoints = initialize_missing_checkpoints(
            checkpoints,
            valid_dynamics,
        )
        checkpoint_changed = bool(initialized_checkpoints)
        for checkpoint in initialized_checkpoints:
            logger.info(
                "Bilibili dynamic checkpoint initialized for "
                f"{checkpoint.author_name} "
                f"({checkpoint.author_mid}): {checkpoint.pub_ts}"
            )

        push_batch = await _push_new_dynamics(
            service,
            valid_dynamics,
            checkpoints,
            send_push,
            cookie=cookie,
        )
        if push_batch.checkpoint_changed:
            checkpoint_changed = True

        if checkpoint_changed:
            service.history.save_checkpoints(checkpoints)
            logger.info("Bilibili dynamic checkpoints updated")

        return MonitorCheckResult(
            executed=True,
            valid_response=True,
            discovered_new=push_batch.discovered_new,
        )

    except Exception:
        logger.exception("Bilibili monitor check failed")
        return result


async def run_monitor_check(  # noqa: PLR0913 - public monitor coordination API
    service: BilibiliService,
    *,
    on_auth_invalid: AuthInvalidHandler,
    send_push: DynamicPushSender,
    is_startup_check: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> MonitorCheckResult:
    current_now = now or datetime.now(timezone.utc).astimezone()
    active_boost_slots = boost_slots_at(service.config.polling, current_now)
    due_boost_slots = boost_slots_due(
        service.auto_check_state,
        active_boost_slots,
    )
    if service.check_lock.locked():
        completed_active_boost = bool(active_boost_slots) and not due_boost_slots
        regular_due = (
            is_startup_check
            or force
            or (
                not active_boost_slots
                and not completed_active_boost
                and auto_check_due(
                    service.auto_check_state,
                    service.config.polling,
                    current_now,
                )
            )
        )
        service.pending_regular_check = (
            service.pending_regular_check or regular_due
        )
        service.pending_boost_slots.update(
            {slot.key: slot for slot in due_boost_slots}
        )
        service.pending_check = (
            service.pending_regular_check or bool(service.pending_boost_slots)
        )
        logger.info(
            "Bilibili dynamic check is already running; regular=%s boost_slots=%s",
            regular_due,
            len(due_boost_slots),
        )
        return MonitorCheckResult()

    async with service.check_lock:
        result = MonitorCheckResult()
        catch_up = force
        while True:
            current_now = now or datetime.now(timezone.utc).astimezone()
            active_boost_slots = boost_slots_at(service.config.polling, current_now)
            pending_boost_slots = tuple(service.pending_boost_slots.values())
            merged_boost_slots = {
                slot.key: slot
                for slot in (*active_boost_slots, *pending_boost_slots)
            }
            due_boost_slots = boost_slots_due(
                service.auto_check_state,
                tuple(merged_boost_slots.values()),
            )
            completed_active_boost = bool(active_boost_slots) and not due_boost_slots
            if not is_startup_check and not catch_up and completed_active_boost:
                return result
            if (
                not is_startup_check
                and not catch_up
                and not due_boost_slots
                and not auto_check_due(
                    service.auto_check_state,
                    service.config.polling,
                    current_now,
                )
            ):
                return result

            service.pending_check = False
            service.pending_regular_check = False
            service.pending_boost_slots.clear()
            started_at = time.monotonic()
            logger.info(
                "Bilibili dynamic discovery check starting: force=%s startup=%s "
                "boost_slots=%s at=%s",
                catch_up,
                is_startup_check,
                len(due_boost_slots),
                current_now.isoformat(),
            )
            result = await _do_check_logic(service, on_auth_invalid, send_push)
            if result.discovered_new and due_boost_slots:
                mark_boost_slots_completed(
                    service.auto_check_state,
                    due_boost_slots,
                    current_now,
                )
                logger.info(
                    "Bilibili release burst completed after new dynamics: slots=%s",
                    ",".join(slot.key for slot in due_boost_slots),
                )
            mark_auto_check(service.auto_check_state, current_now)
            logger.info(
                "Bilibili dynamic discovery check completed: valid=%s new=%s "
                "elapsed=%.3fs",
                result.valid_response,
                result.discovered_new,
                time.monotonic() - started_at,
            )
            is_startup_check = False
            if not service.pending_check:
                break
            pending_boost_slots = boost_slots_due(
                service.auto_check_state,
                tuple(service.pending_boost_slots.values()),
            )
            if not service.pending_regular_check and not pending_boost_slots:
                service.pending_check = False
                service.pending_boost_slots.clear()
                break
            logger.info("Bilibili dynamic catch-up check starting")
            catch_up = True

    return result
