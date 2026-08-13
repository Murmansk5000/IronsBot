import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.categories import classify_dynamic
from ironsbot.services.bilibili.checkpoints import (
    DynamicItem,
    initialize_missing_checkpoints,
    mark_checkpoint,
)
from ironsbot.services.bilibili.parser import (
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
    [dict[str, Any], int, int, BiliPushTargets],
    Awaitable[None],
]


@dataclass(frozen=True, slots=True)
class DynamicPushBatch:
    checkpoint_changed: bool
    discovered_new: bool = False


@dataclass(frozen=True, slots=True)
class MonitorCheckResult:
    executed: bool = False
    valid_response: bool = False
    discovered_new: bool = False

    def __bool__(self) -> bool:
        return self.executed


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
) -> DynamicPushBatch:
    checkpoint_changed = False
    discovered_new = False
    for pub_ts, item in valid_dynamics:
        author_mid = item_author_mid(item)
        category_config = service.targets.category_config_for_uid(author_mid)
        categories = classify_dynamic(item, category_config)
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=service.targets.suppress_patterns_for_uid(author_mid),
        )
        if snapshot is None:
            continue

        author_mid = snapshot.author_mid
        last_saved_time = checkpoints.get(author_mid, 0)
        service.history.save_snapshot(snapshot)
        targets: BiliPushTargets | None = None
        decision = decide_dynamic_push_before_targets(
            pub_ts=pub_ts,
            last_saved_time=last_saved_time,
            suppression_reason=snapshot.suppression_reason,
        )
        if decision is None:
            targets = service.targets.push_targets_for_dynamic(
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
            checkpoint_changed = (
                mark_checkpoint(checkpoints, author_mid, pub_ts) or checkpoint_changed
            )
            continue

        if targets is None:
            targets = service.targets.push_targets_for_dynamic(
                author_mid,
                categories=categories,
            )

        await send_push(
            item,
            pub_ts,
            author_mid,
            targets,
        )
        service.history.save_snapshot(mark_history_snapshot_pushed(snapshot))
        checkpoint_changed = (
            mark_checkpoint(checkpoints, author_mid, pub_ts) or checkpoint_changed
        )

    return DynamicPushBatch(checkpoint_changed, discovered_new)


async def _do_check_logic(
    service: BilibiliService,
    on_auth_invalid: AuthInvalidHandler,
    send_push: DynamicPushSender,
) -> MonitorCheckResult:
    result = MonitorCheckResult(executed=True)
    try:
        feed = await service.fetch_feed(service.cookie_store.load())
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


async def run_monitor_check(  # noqa: PLR0913 - monitor coordination boundary
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
    due_boost_slots = boost_slots_due(service.auto_check_state, active_boost_slots)
    if service.check_lock.locked():
        completed_active_boost = bool(active_boost_slots) and not due_boost_slots
        regular_due = (
            is_startup_check
            or force
            or (
                not active_boost_slots
                and not completed_active_boost
                and auto_check_due(
                    service.auto_check_state, service.config.polling, current_now
                )
            )
        )
        service.pending_regular_check = service.pending_regular_check or regular_due
        service.pending_boost_slots.update({slot.key: slot for slot in due_boost_slots})
        service.pending_check = service.pending_regular_check or bool(
            service.pending_boost_slots
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
            merged_slots = {
                slot.key: slot
                for slot in (*active_boost_slots, *service.pending_boost_slots.values())
            }
            due_boost_slots = boost_slots_due(
                service.auto_check_state,
                tuple(merged_slots.values()),
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
            result = await _do_check_logic(service, on_auth_invalid, send_push)
            if result.discovered_new and due_boost_slots:
                mark_boost_slots_completed(
                    service.auto_check_state,
                    due_boost_slots,
                    current_now,
                )
            mark_auto_check(service.auto_check_state, current_now)
            is_startup_check = False
            if not service.pending_check:
                break
            pending_slots = boost_slots_due(
                service.auto_check_state,
                tuple(service.pending_boost_slots.values()),
            )
            if not service.pending_regular_check and not pending_slots:
                service.pending_check = False
                service.pending_boost_slots.clear()
                break
            catch_up = True

    return result
