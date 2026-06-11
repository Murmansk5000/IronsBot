from datetime import datetime, timezone
from typing import Any

from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.services.bilibili.cache import (
    get_last_saved_times,
    get_saved_cookie,
    save_dynamic_history_snapshot,
    save_last_saved_times,
)
from ironsbot.services.bilibili.checkpoints import (
    DynamicItem,
    initialize_missing_checkpoints,
    mark_checkpoint,
)
from ironsbot.services.bilibili.client import fetch_dynamic_feed
from ironsbot.services.bilibili.delivery import build_dynamic_push_deliveries
from ironsbot.services.bilibili.parser import (
    target_dynamics_from_response,
)
from ironsbot.services.bilibili.push import (
    DynamicHistorySnapshot,
    build_dynamic_history_snapshot_for_item,
    decide_dynamic_push_after_targets,
    decide_dynamic_push_before_targets,
    mark_history_snapshot_pushed,
)
from ironsbot.services.bilibili.responses import check_dynamic_response
from ironsbot.services.bilibili.schedule import (
    AutoCheckState,
    auto_check_due,
    mark_auto_check,
)
from ironsbot.services.bilibili.state import (
    BiliPushTargets,
    check_lock,
    monitored_uids,
    push_targets_for_uid,
)

from .auth import send_bili_login_qrcode_to_superusers
from .bot_access import get_first_bot
from .config import get_bili_config

DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2


_auto_check_state = AutoCheckState()


async def _is_valid_dynamic_response(response: Any, res_json: dict[str, Any]) -> bool:
    check = check_dynamic_response(response.status_code, res_json)
    if check.is_ok:
        return True

    if check.status == "auth_invalid":
        await send_bili_login_qrcode_to_superusers(
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
    bot: Bot,
    item: dict[str, Any],
    pub_ts: int,
    targets: BiliPushTargets,
) -> None:
    from ironsbot.custom_plugins.message_actions import send_broadcast_message

    for delivery in build_dynamic_push_deliveries(item, pub_ts, targets):
        await send_broadcast_message(
            delivery.message,
            group_ids=delivery.group_ids,
            private_user_ids=delivery.private_user_ids,
            bot=bot,
            action_name=delivery.action_name,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
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
    valid_dynamics: list[DynamicItem],
    checkpoints: dict[int, int],
) -> bool:
    checkpoint_changed = False
    bot: Bot | None = None
    for pub_ts, item in valid_dynamics:
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=get_bili_config().filters.suppress_push_patterns,
        )
        if snapshot is None:
            continue

        author_mid = snapshot.author_mid
        last_saved_time = checkpoints.get(author_mid, 0)
        save_dynamic_history_snapshot(snapshot)
        targets: BiliPushTargets | None = None
        decision = decide_dynamic_push_before_targets(
            pub_ts=pub_ts,
            last_saved_time=last_saved_time,
            suppression_reason=snapshot.suppression_reason,
        )
        if decision is None:
            targets = push_targets_for_uid(author_mid)
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
            targets = push_targets_for_uid(author_mid)

        bot = bot or get_first_bot()
        if not bot:
            logger.warning("no bot online for Bilibili dynamic push")
            return checkpoint_changed

        await _send_dynamic_push(bot, item, pub_ts, targets)
        save_dynamic_history_snapshot(mark_history_snapshot_pushed(snapshot))
        checkpoint_changed = (
            mark_checkpoint(checkpoints, author_mid, pub_ts)
            or checkpoint_changed
        )

    return checkpoint_changed


async def _do_check_logic() -> None:
    try:
        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if not await _is_valid_dynamic_response(response, res_json):
            return

        valid_dynamics = target_dynamics_from_response(
            res_json,
            monitored_uids(),
        )
        if not valid_dynamics:
            return

        checkpoints = get_last_saved_times()
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

        if await _push_new_dynamics(valid_dynamics, checkpoints):
            checkpoint_changed = True

        if checkpoint_changed:
            save_last_saved_times(checkpoints)
            logger.info("Bilibili dynamic checkpoints updated")

    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili monitor check failed: {e}")


async def run_check_logic(
    *,
    is_startup_check: bool = False,
    force: bool = False,
) -> bool:
    if check_lock.locked():
        logger.info("Bilibili dynamic check is already running")
        return False

    async with check_lock:
        now = datetime.now(timezone.utc).astimezone()
        if (
            not is_startup_check
            and not force
            and not auto_check_due(
                _auto_check_state,
                get_bili_config().polling,
                now,
            )
        ):
            return False

        await _do_check_logic()
        mark_auto_check(_auto_check_state, now)

    return True
