from pathlib import Path

from ironsbot.services.bilibili.accounts import get_bili_config
from ironsbot.services.bilibili.preferences import BiliPushPreferenceStore


def bili_storage_dir() -> Path:
    return get_bili_config().storage.data_dir


def dynamic_history_db_file() -> Path:
    return bili_storage_dir() / "dynamic_history.sqlite"


def cookie_cache_file() -> Path:
    return bili_storage_dir() / "bili_cookie_cache.txt"


def push_preferences_db_file() -> Path:
    return bili_storage_dir() / "push_preferences.sqlite"


def push_preference_store() -> BiliPushPreferenceStore:
    return BiliPushPreferenceStore(push_preferences_db_file())
