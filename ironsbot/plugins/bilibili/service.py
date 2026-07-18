from datetime import datetime, timezone
from functools import partial
from typing import Any

from nonebot.log import logger

from ironsbot.services.bilibili.checkpoints import (
    DynamicItem,
    initialize_missing_checkpoints,
    mark_checkpoint,
)
from ironsbot.services.bilibili.client import fetch_dynamic_feed
from ironsbot.services.bilibili.delivery import (
    append_bili_admin_hint_for_group,
    build_dynamic_push_deliveries,
)
from ironsbot.services.bilibili.parser import (
    target_dynamics_from_response,
)
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.bilibili.push import (
    DynamicHistorySnapshot,
    build_dynamic_history_snapshot_for_item,
    decide_dynamic_push_after_targets,
    decide_dynamic_push_before_targets,
    mark_history_snapshot_pushed,
)
from ironsbot.services.bilibili.resources import BilibiliResources
from ironsbot.services.bilibili.responses import check_dynamic_response
from ironsbot.services.bilibili.schedule import (
    auto_check_due,
    mark_auto_check,
)
from ironsbot.services.bilibili.targets import BiliPushTargets

from .auth import send_bili_login_qrcode_to_superusers

DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2


async def _is_valid_dynamic_response(
    resources: BilibiliResources,
    response: Any,
    res_json: dict[str, Any],
) -> bool:
    check = check_dynamic_response(response.status_code, res_json)
    if check.is_ok:
        return True

    if check.status == "auth_invalid":
        await send_bili_login_qrcode_to_superusers(
            resources,
            "自动检查动态时发现 B 站登录失效"
        )
        return False

    if check.status == "http_error":
        logger.warning(
            f"Bilibili dynamic API returned HTTP {check.http_status}"
        )
        return False

    logger.warning(f"Bilibili dynamic API returned code {check.api_code}")
    return False


async def _send_dynamic_push(
    resources: BilibiliResources,
    item: dict[str, Any],
    pub_ts: int,
    author_mid: int,
    targets: BiliPushTargets,
) -> None:
    from ironsbot.shared.messaging import send_broadcast_message

    for delivery in build_dynamic_push_deliveries(
        resources.admin_notices.features,
        item,
        pub_ts,
        targets,
    ):
        await send_broadcast_message(
            resources.admin_notices.delivery,
            delivery.message,
            group_ids=delivery.group_ids,
            private_user_ids=delivery.private_user_ids,
            action_name=delivery.action_name,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            message_limiter=partial(
                append_bili_admin_hint_for_group,
                resources.targets.unsubscribe_store,
            ),
            subscription_key=bili_push_subscription_key(author_mid),
        )


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
    resources: BilibiliResources,
    valid_dynamics: list[DynamicItem],
    checkpoints: dict[int, int],
) -> bool:
    checkpoint_changed = False
    for pub_ts, item in valid_dynamics:
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=resources.config.filters.suppress_push_patterns,
        )
        if snapshot is None:
            continue

        author_mid = snapshot.author_mid
        last_saved_time = checkpoints.get(author_mid, 0)
        resources.history.save_snapshot(snapshot)
        targets: BiliPushTargets | None = None
        decision = decide_dynamic_push_before_targets(
            pub_ts=pub_ts,
            last_saved_time=last_saved_time,
            suppression_reason=snapshot.suppression_reason,
        )
        if decision is None:
            targets = resources.targets.push_targets_for_uid(author_mid)
            decision = decide_dynamic_push_after_targets(targets)

        if decision.status == "skip_existing":
            continue

        if decision.status in {"suppressed", "no_targets"}:
            _log_non_delivery_decision(decision.status, snapshot)
            checkpoint_changed = (
                mark_checkpoint(checkpoints, author_mid, pub_ts)
                or checkpoint_changed
            )
            continue

        if targets is None:
            targets = resources.targets.push_targets_for_uid(author_mid)

        await _send_dynamic_push(
            resources,
            item,
            pub_ts,
            author_mid,
            targets,
        )
        resources.history.save_snapshot(mark_history_snapshot_pushed(snapshot))
        checkpoint_changed = (
            mark_checkpoint(checkpoints, author_mid, pub_ts)
            or checkpoint_changed
        )

    return checkpoint_changed


async def _do_check_logic(
    resources: BilibiliResources,
) -> None:
    try:
        response, res_json = await fetch_dynamic_feed(
            resources.cookie_store.load()
        )
        if not await _is_valid_dynamic_response(
            resources,
            response,
            res_json,
        ):
            return

        valid_dynamics = target_dynamics_from_response(
            res_json,
            resources.targets.monitored_uids(),
        )
        if not valid_dynamics:
            return

        checkpoints = resources.history.get_checkpoints()
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
            resources,
            valid_dynamics,
            checkpoints,
        ):
            checkpoint_changed = True

        if checkpoint_changed:
            resources.history.save_checkpoints(checkpoints)
            logger.info("Bilibili dynamic checkpoints updated")

    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili monitor check failed: {e}")


async def run_check_logic(
    resources: BilibiliResources,
    *,
    is_startup_check: bool = False,
    force: bool = False,
) -> bool:
    if resources.check_lock.locked():
        logger.info("Bilibili dynamic check is already running")
        return False

    async with resources.check_lock:
        now = datetime.now(timezone.utc).astimezone()
        if (
            not is_startup_check
            and not force
            and not auto_check_due(
                resources.auto_check_state,
                resources.config.polling,
                now,
            )
        ):
            return False

        await _do_check_logic(resources)
        mark_auto_check(resources.auto_check_state, now)

    return True
