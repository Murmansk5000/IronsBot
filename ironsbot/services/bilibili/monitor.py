import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

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
    mark_auto_check,
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
) -> bool:
    checkpoint_changed = False
    for pub_ts, item in valid_dynamics:
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

        if not service.history.try_claim_delivery(history_id):
            logger.info(
                "Bilibili dynamic delivery is already claimed; skipping %s (%s): %s",
                snapshot.author_name,
                author_mid,
                history_id,
            )
            continue

        try:
            await send_push(
                item,
                pub_ts,
                author_mid,
                targets,
            )
        except BaseException:
            service.history.release_delivery_claim(history_id)
            raise
        service.history.save_snapshot(mark_history_snapshot_pushed(snapshot))
        checkpoint_changed = (
            mark_checkpoint(checkpoints, author_mid, pub_ts) or checkpoint_changed
        )

    return checkpoint_changed


async def _do_check_logic(
    service: BilibiliService,
    on_auth_invalid: AuthInvalidHandler,
    send_push: DynamicPushSender,
) -> None:
    try:
        feed = await service.fetch_feed(service.cookie_store.load())
        if not await _is_valid_dynamic_response(
            feed,
            on_auth_invalid,
        ):
            return

        valid_dynamics = target_dynamics_from_response(
            feed.data,
            service.targets.monitored_uids(),
        )
        if not valid_dynamics:
            return

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

        if await _push_new_dynamics(
            service,
            valid_dynamics,
            checkpoints,
            send_push,
        ):
            checkpoint_changed = True

        if checkpoint_changed:
            service.history.save_checkpoints(checkpoints)
            logger.info("Bilibili dynamic checkpoints updated")

    except Exception:
        logger.exception("Bilibili monitor check failed")


async def run_monitor_check(
    service: BilibiliService,
    *,
    on_auth_invalid: AuthInvalidHandler,
    send_push: DynamicPushSender,
    is_startup_check: bool = False,
    force: bool = False,
) -> bool:
    if service.check_lock.locked():
        logger.info("Bilibili dynamic check is already running")
        return False

    async with service.check_lock:
        now = datetime.now(timezone.utc).astimezone()
        if (
            not is_startup_check
            and not force
            and not auto_check_due(
                service.auto_check_state,
                service.config.polling,
                now,
            )
        ):
            return False

        await _do_check_logic(service, on_auth_invalid, send_push)
        mark_auto_check(service.auto_check_state, now)

    return True
