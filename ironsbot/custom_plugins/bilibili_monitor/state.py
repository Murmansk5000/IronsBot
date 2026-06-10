import asyncio

from ironsbot.custom_plugins.feature_policy import (
    groups_for_feature,
    resolve_group_refs,
    resolve_user_refs,
    users_for_feature,
    users_with_superusers,
)

from .config import plugin_config


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


BILI_CONFIG = plugin_config.bili_config
MONITORED_UIDS = _unique_ints(BILI_CONFIG.uids)

TARGET_GROUP_IDS = groups_for_feature("bili_push")
TARGET_USER_IDS = list(
    dict.fromkeys(users_with_superusers(users_for_feature("bili_push")))
)
LINK_ONLY_GROUP_IDS = resolve_group_refs(BILI_CONFIG.push.link_only_groups)
LINK_ONLY_USER_IDS = resolve_user_refs(BILI_CONFIG.push.link_only_users)

BILI_STORAGE_DIR = BILI_CONFIG.storage.data_dir
BILI_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DYNAMIC_HISTORY_DB_FILE = BILI_STORAGE_DIR / "dynamic_history.sqlite"
COOKIE_CACHE_FILE = BILI_STORAGE_DIR / "bili_cookie_cache.txt"

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
