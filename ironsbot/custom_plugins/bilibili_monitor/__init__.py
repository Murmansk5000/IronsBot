from nonebot.plugin import PluginMetadata

from ironsbot.custom_plugins.startup_ready import wait_startup_ready

from . import commands as commands
from .auth import (
    is_bili_auth_invalid,
    is_bili_login_required,
    request_bili_login_qrcode,
    send_bili_login_qrcode_to_superusers,
)
from .cache import (
    get_last_saved_times,
    get_saved_cookie,
    save_last_saved_times,
    save_new_cookie,
)
from .config import Config
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
from .state import BILI_UIDS, TARGET_GROUP_IDS, TARGET_USER_IDS

__plugin_meta__ = PluginMetadata(
    name="B站动态",
    description="查询、刷新和自动推送配置账号的 Bilibili 动态",
    usage=(
        "【B站动态】\n"
        "动态 — 拉取最新动态列表，继续发送数字查看详情\n"
        "/动态更新、/动态刷新 — 超级管理员手动刷新并推送新动态\n"
        "二维码登录、Cookie 保存和自动推送由插件自动处理。"
    ),
    config=Config,
)


async def wait_startup_check_done() -> None:
    await wait_startup_ready()


__all__ = [
    "BILI_UIDS",
    "TARGET_GROUP_IDS",
    "TARGET_USER_IDS",
    "commands",
    "get_bili_superuser_uids",
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
    "save_last_saved_times",
    "save_new_cookie",
    "scan_and_swallow_all_long_strings",
    "send_bili_login_qrcode_to_superusers",
    "wait_startup_check_done",
]
