import asyncio

from ironsbot.custom_plugins.feature_policy import (
    groups_for_feature,
    users_for_feature,
    users_with_superusers,
)

from .config import plugin_config


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


BILI_UIDS = _unique_ints(plugin_config.bili_uids)
CHECK_INTERVAL_MINUTES = plugin_config.bili_check_minutes
SLEEP_START_HOUR = plugin_config.bili_sleep_start
SLEEP_END_HOUR = plugin_config.bili_sleep_end
SLEEP_INTERVAL_MINUTES = plugin_config.bili_sleep_minutes

TARGET_GROUP_IDS = groups_for_feature("bili_push")
TARGET_USER_IDS = list(
    dict.fromkeys(users_with_superusers(users_for_feature("bili_push")))
)

BILI_DATA_DIR = plugin_config.bili_data_dir
BILI_DATA_DIR.mkdir(parents=True, exist_ok=True)

DYNAMIC_HISTORY_DB_FILE = BILI_DATA_DIR / "dynamic_history.sqlite"
COOKIE_CACHE_FILE = BILI_DATA_DIR / "bili_cookie_cache.txt"

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
