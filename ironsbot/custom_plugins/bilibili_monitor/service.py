import asyncio
from datetime import datetime, timezone
from typing import Any

from nonebot import require
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.startup_ready import register_startup_check

from .auth import is_bili_auth_invalid, send_bili_login_qrcode_to_superusers
from .bot_access import get_first_bot
from .cache import (
    get_last_saved_times,
    get_saved_cookie,
    save_dynamic_history_item,
    save_last_saved_times,
)
from .client import fetch_dynamic_feed
from .parser import (
    dynamic_brief,
    find_target_dynamics,
    item_author_mid,
    item_author_name,
    parse_single_item,
)
from .state import (
    CHECK_INTERVAL_MINUTES,
    SLEEP_END_HOUR,
    SLEEP_INTERVAL_MINUTES,
    SLEEP_START_HOUR,
    TARGET_GROUP_IDS,
    TARGET_USER_IDS,
    check_lock,
)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

HTTP_OK = 200
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
DynamicItem = tuple[int, dict[str, Any]]


def _should_skip_for_sleep_window(
    now: datetime,
    *,
    is_startup_check: bool,
) -> bool:
    if not (now.hour >= SLEEP_START_HOUR or now.hour < SLEEP_END_HOUR):
        return False

    return (
        not is_startup_check
        and now.minute % SLEEP_INTERVAL_MINUTES != 0
    )


async def _is_valid_dynamic_response(response: Any, res_json: dict[str, Any]) -> bool:
    if is_bili_auth_invalid(response.status_code, res_json):
        await send_bili_login_qrcode_to_superusers(
            "自动检查动态时发现B站登录失效"
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
        save_dynamic_history_item(
            item,
            pub_ts=pub_ts,
            author_mid=author_mid,
            author_name=item_author_name(item),
            brief=dynamic_brief(item),
            pushed=should_push,
        )
        if not should_push:
            continue

        message = parse_single_item(item, pub_ts)
        if not message:
            continue

        bot = bot or get_first_bot()
        if not bot:
            logger.warning("no bot online for Bilibili dynamic push")
            return checkpoint_changed

        await send_broadcast_message(
            message,
            group_ids=TARGET_GROUP_IDS,
            private_user_ids=TARGET_USER_IDS,
            bot=bot,
            action_name="Bilibili dynamic push",
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
        )
        checkpoints[author_mid] = max(checkpoints.get(author_mid, 0), pub_ts)
        checkpoint_changed = True

    return checkpoint_changed


async def _do_check_logic(*, is_startup_check: bool = False) -> None:
    now = datetime.now(timezone.utc).astimezone()
    if _should_skip_for_sleep_window(now, is_startup_check=is_startup_check):
        logger.info(f"Bilibili monitor skipped in sleep window: {now:%H:%M}")
        return

    try:
        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if not await _is_valid_dynamic_response(response, res_json):
            return

        valid_dynamics = find_target_dynamics(
            res_json.get("data", {}).get("items", [])
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


async def run_check_logic(*, is_startup_check: bool = False) -> bool:
    if check_lock.locked():
        logger.info("Bilibili dynamic check is already running")
        return False

    async with check_lock:
        await _do_check_logic(is_startup_check=is_startup_check)

    return True


@scheduler.scheduled_job("interval", minutes=CHECK_INTERVAL_MINUTES)
async def auto_check_job() -> None:
    await run_check_logic()


async def _startup_check(bot: Bot) -> None:
    logger.info(f"Bilibili monitor saw bot connected: {bot.self_id}")
    await asyncio.sleep(2)
    await run_check_logic(is_startup_check=True)


register_startup_check("bilibili_monitor", _startup_check)
