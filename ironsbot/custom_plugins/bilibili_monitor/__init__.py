from ironsbot.custom_plugins.startup_ready import wait_startup_ready

from .auth import (
    is_bili_auth_invalid,
    is_bili_login_required,
    request_bili_login_qrcode,
    send_bili_login_qrcode_to_superusers,
)
from .cache import (
    get_last_saved_time,
    get_last_saved_times,
    get_saved_cookie,
    migrate_legacy_cache_files,
    save_last_time,
    save_last_saved_times,
    save_new_cookie,
)
from .parser import (
    item_author_label,
    item_author_mid,
    item_author_name,
    parse_single_item,
    scan_and_swallow_all_long_strings,
)
from .permissions import (
    get_bili_superuser_uids,
    is_bili_superuser,
)
from .service import run_check_logic
from .state import BILI_UID, BILI_UIDS, TARGET_GROUP_IDS, TARGET_USER_IDS

migrate_legacy_cache_files()


async def wait_startup_check_done() -> None:
    await wait_startup_ready()


from . import commands as commands

__all__ = [
    "BILI_UID",
    "BILI_UIDS",
    "TARGET_GROUP_IDS",
    "TARGET_USER_IDS",
    "commands",
    "get_bili_superuser_uids",
    "get_last_saved_time",
    "get_last_saved_times",
    "get_saved_cookie",
    "is_bili_auth_invalid",
    "is_bili_login_required",
    "is_bili_superuser",
    "item_author_label",
    "item_author_mid",
    "item_author_name",
    "parse_single_item",
    "request_bili_login_qrcode",
    "run_check_logic",
    "save_last_time",
    "save_last_saved_times",
    "save_new_cookie",
    "scan_and_swallow_all_long_strings",
    "send_bili_login_qrcode_to_superusers",
    "wait_startup_check_done",
]
