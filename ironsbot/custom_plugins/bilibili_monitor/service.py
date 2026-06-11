import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from nonebot import get_driver, require
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.custom_plugins.startup_ready import register_startup_check
from ironsbot.services.bilibili.cache import (
    get_last_saved_times,
    get_saved_cookie,
    save_dynamic_history_item,
    save_last_saved_times,
)
from ironsbot.services.bilibili.parser import (
    dynamic_brief,
    dynamic_suppression_reason,
    find_target_dynamics,
    item_author_mid,
    item_author_name,
    parse_single_item,
)
from ironsbot.services.bilibili.state import (
    BiliPushTargets,
    check_lock,
    monitored_uids,
    push_targets_for_uid,
)
from ironsbot.shared.config.time import minute_of_day

from .auth import is_bili_auth_invalid, send_bili_login_qrcode_to_superusers
from .bot_access import get_first_bot
from .client import fetch_dynamic_feed
from .config import get_bili_config

HTTP_OK = 200
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
DynamicItem = tuple[int, dict[str, Any]]


@dataclass(slots=True)
class AutoCheckState:
    last_checked_at: datetime | None = None


_auto_check_state = AutoCheckState()
_bilibili_monitor_runtime_state = {"registered": False}


def _window_contains(now: datetime, *, start: str, end: str) -> bool:
    current = now.hour * 60 + now.minute
    error_message = "bilibili.polling.windows time must use HH:MM"
    start_minute = minute_of_day(start, error_message=error_message)
    end_minute = minute_of_day(end, error_message=error_message)
    if start_minute <= end_minute:
        return start_minute <= current < end_minute
    return current >= start_minute or current < end_minute


def _current_interval_minutes(now: datetime) -> int:
    config = get_bili_config()
    for window in config.polling.windows:
        if _window_contains(now, start=window.start, end=window.end):
            return window.minutes
    return config.polling.default_minutes


def _auto_check_due(now: datetime) -> bool:
    if _auto_check_state.last_checked_at is None:
        return True
    interval = _current_interval_minutes(now)
    elapsed = now - _auto_check_state.last_checked_at
    return elapsed.total_seconds() >= interval * 60


async def _is_valid_dynamic_response(response: Any, res_json: dict[str, Any]) -> bool:
    if is_bili_auth_invalid(response.status_code, res_json):
        await send_bili_login_qrcode_to_superusers(
            "自动检查动态时发现 B 站登录失效"
        )
        return False

    if response.status_code != HTTP_OK:
        logger.warning(
            f"Bilibili dynamic API returned HTTP {response.status_code}"
        )
        return False

    if res_json.get("code") != 0:
        logger.warning(
            f"Bilibili dynamic API returned code {res_json.get('code')}"
        )
        return False

    return True


def _latest_seen_by_uid(valid_dynamics: list[DynamicItem]) -> dict[int, DynamicItem]:
    latest_seen: dict[int, DynamicItem] = {}
    for pub_ts, item in valid_dynamics:
        author_mid = item_author_mid(item)
        if not author_mid:
            continue

        saved_pub_ts, _ = latest_seen.get(author_mid, (0, {}))
        if pub_ts > saved_pub_ts:
            latest_seen[author_mid] = (pub_ts, item)

    return latest_seen


def _initialize_missing_checkpoints(
    checkpoints: dict[int, int],
    valid_dynamics: list[DynamicItem],
) -> bool:
    checkpoint_changed = False
    for author_mid, (pub_ts, item) in _latest_seen_by_uid(valid_dynamics).items():
        if checkpoints.get(author_mid, 0) > 0:
            continue

        checkpoints[author_mid] = pub_ts
        checkpoint_changed = True
        logger.info(
            "Bilibili dynamic checkpoint initialized for "
            f"{item_author_name(item)} ({author_mid}): {pub_ts}"
        )

    return checkpoint_changed


async def _send_dynamic_push(
    bot: Bot,
    item: dict[str, Any],
    pub_ts: int,
    targets: BiliPushTargets,
) -> None:
    from ironsbot.custom_plugins.message_actions import send_broadcast_message

    if targets.full_group_ids or targets.full_user_ids:
        full_message = parse_single_item(item, pub_ts, mode="full")
        if full_message:
            await send_broadcast_message(
                full_message,
                group_ids=targets.full_group_ids,
                private_user_ids=targets.full_user_ids,
                bot=bot,
                action_name="Bilibili dynamic push",
                interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            )

    if targets.link_group_ids or targets.link_user_ids:
        link_message = parse_single_item(item, pub_ts, mode="link")
        if link_message:
            await send_broadcast_message(
                link_message,
                group_ids=targets.link_group_ids,
                private_user_ids=targets.link_user_ids,
                bot=bot,
                action_name="Bilibili dynamic link push",
                interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            )


def _mark_checkpoint(
    checkpoints: dict[int, int],
    author_mid: int,
    pub_ts: int,
) -> bool:
    old_value = checkpoints.get(author_mid, 0)
    checkpoints[author_mid] = max(old_value, pub_ts)
    return checkpoints[author_mid] != old_value


async def _push_new_dynamics(
    valid_dynamics: list[DynamicItem],
    checkpoints: dict[int, int],
) -> bool:
    checkpoint_changed = False
    bot: Bot | None = None
    for pub_ts, item in valid_dynamics:
        author_mid = item_author_mid(item)
        if not author_mid:
            continue

        last_saved_time = checkpoints.get(author_mid, 0)
        should_push = pub_ts > last_saved_time
        suppression_reason = dynamic_suppression_reason(
            item,
            get_bili_config().filters.suppress_push_patterns,
        )
        save_dynamic_history_item(
            item,
            pub_ts=pub_ts,
            author_mid=author_mid,
            author_name=item_author_name(item),
            brief=dynamic_brief(item),
            suppressed=bool(suppression_reason),
            suppression_reason=suppression_reason,
        )
        if not should_push:
            continue

        if suppression_reason:
            logger.info(
                "Bilibili dynamic push suppressed for "
                f"{item_author_name(item)} ({author_mid}): {suppression_reason}"
            )
            if _mark_checkpoint(checkpoints, author_mid, pub_ts):
                checkpoint_changed = True
            continue

        targets = push_targets_for_uid(author_mid)
        if not targets.has_targets:
            logger.info(
                "Bilibili dynamic saved without push target for "
                f"{item_author_name(item)} ({author_mid})"
            )
            if _mark_checkpoint(checkpoints, author_mid, pub_ts):
                checkpoint_changed = True
            continue

        bot = bot or get_first_bot()
        if not bot:
            logger.warning("no bot online for Bilibili dynamic push")
            return checkpoint_changed

        await _send_dynamic_push(bot, item, pub_ts, targets)
        save_dynamic_history_item(
            item,
            pub_ts=pub_ts,
            author_mid=author_mid,
            author_name=item_author_name(item),
            brief=dynamic_brief(item),
            pushed=True,
        )
        if _mark_checkpoint(checkpoints, author_mid, pub_ts):
            checkpoint_changed = True

    return checkpoint_changed


async def _do_check_logic() -> None:
    try:
        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if not await _is_valid_dynamic_response(response, res_json):
            return

        valid_dynamics = find_target_dynamics(
            res_json.get("data", {}).get("items", []),
            monitored_uids(),
        )
        if not valid_dynamics:
            return

        valid_dynamics.sort(key=lambda value: value[0])
        checkpoints = get_last_saved_times()
        checkpoint_changed = _initialize_missing_checkpoints(
            checkpoints,
            valid_dynamics,
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
        if not is_startup_check and not force and not _auto_check_due(now):
            return False

        await _do_check_logic()
        _auto_check_state.last_checked_at = now

    return True


async def auto_check_job() -> None:
    await run_check_logic()


async def register_bili_auto_check_job(scheduler: Any) -> None:
    scheduler.add_job(
        auto_check_job,
        "interval",
        minutes=1,
        id="bilibili_monitor_auto_check",
        replace_existing=True,
    )


async def _startup_check(bot: Bot) -> None:
    logger.info(f"Bilibili monitor saw bot connected: {bot.self_id}")
    await asyncio.sleep(2)
    await run_check_logic(is_startup_check=True)


def _setup_bilibili_monitor_runtime(driver: Any, scheduler: Any) -> None:
    if _bilibili_monitor_runtime_state["registered"]:
        return

    register_startup_check("bilibili_monitor", _startup_check)

    @driver.on_startup
    async def _register_bili_auto_check_on_startup() -> None:
        await register_bili_auto_check_job(scheduler)

    _bilibili_monitor_runtime_state["registered"] = True


def setup_bilibili_monitor_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_bilibili_monitor_runtime(get_driver(), scheduler)
