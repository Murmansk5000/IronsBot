import asyncio
from pathlib import Path

from ironsbot.custom_plugins.superuser_policy import (
    with_superuser_groups,
    with_superusers,
)

from .config import plugin_config

def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


BILI_UID = plugin_config.bilibili_monitor_uid
BILI_UIDS = _unique_ints(
    plugin_config.bilibili_monitor_uids
    or [BILI_UID]
)
CHECK_INTERVAL_MINUTES = plugin_config.bilibili_monitor_check_interval_minutes
SLEEP_START_HOUR = plugin_config.bilibili_monitor_sleep_start_hour
SLEEP_END_HOUR = plugin_config.bilibili_monitor_sleep_end_hour
SLEEP_INTERVAL_MINUTES = plugin_config.bilibili_monitor_sleep_interval_minutes

TARGET_GROUP_IDS = list(
    dict.fromkeys(with_superuser_groups(plugin_config.bilibili_monitor_target_group_ids))
)
TARGET_USER_IDS = list(
    dict.fromkeys(with_superusers(plugin_config.bilibili_monitor_target_user_ids))
)

BILI_DATA_DIR = plugin_config.bilibili_monitor_data_dir
BILI_DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE = BILI_DATA_DIR / "last_dynamic_time.txt"
CHECKPOINTS_FILE = BILI_DATA_DIR / "dynamic_checkpoints.json"
COOKIE_CACHE_FILE = BILI_DATA_DIR / "bili_cookie_cache.txt"
LEGACY_CACHE_FILE = Path(__file__).parent / "last_dynamic_time.txt"
LEGACY_COOKIE_CACHE_FILE = Path(__file__).parent / "bili_cookie_cache.txt"

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_NOTICE_COOLDOWN_SECONDS = 5 * 60
LOGIN_QR_EXPIRE_SECONDS = 180
LOGIN_COOKIE_KEYS = {
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
}

check_lock = asyncio.Lock()
