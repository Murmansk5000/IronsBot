from nonebot.plugin import PluginMetadata

from ironsbot.shared.plugin_runtime.startup_ready import wait_startup_ready
from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.cache import (
    get_dynamic_history_item,
    get_last_saved_times,
    get_saved_cookie,
    list_dynamic_history,
    save_last_saved_times,
    save_new_cookie,
)
from ironsbot.services.bilibili.parser import (
    item_author_label,
    item_author_mid,
    item_author_name,
    parse_single_item,
    scan_and_swallow_all_long_strings,
)
from ironsbot.services.bilibili.permissions import (
    get_bili_superuser_uids,
    is_bili_superuser,
)
from ironsbot.services.bilibili.state import (
    monitored_uids,
    target_group_ids,
    target_user_ids,
)

from . import commands as commands
from .auth import (
    is_bili_login_required,
    request_bili_login_qrcode,
    send_bili_login_qrcode_to_superusers,
)
from .config import Config
from .service import run_check_logic

__plugin_meta__ = PluginMetadata(
    name="B站动态",
    description="查询、刷新和自动推送配置账号的 Bilibili 动态",
    usage=(
        "【B站动态】\n"
        "动态：拉取当前会话订阅账号的最新动态列表，继续发送数字查看详情。\n"
        "/动态更新、/动态刷新：超级管理员手动刷新并推送新动态。\n"
        "自动推送支持按群/用户/UID 配置全文或只发链接；抽奖中奖结果不推送，"
        "但仍可在历史动态里查询。"
    ),
    config=Config,
)


async def wait_startup_check_done() -> None:
    await wait_startup_ready()


__all__ = [
    "commands",
    "get_bili_superuser_uids",
    "get_dynamic_history_item",
    "get_last_saved_times",
    "get_saved_cookie",
    "is_bili_auth_invalid",
    "is_bili_login_required",
    "is_bili_superuser",
    "item_author_label",
    "item_author_mid",
    "item_author_name",
    "list_dynamic_history",
    "monitored_uids",
    "parse_single_item",
    "request_bili_login_qrcode",
    "run_check_logic",
    "save_last_saved_times",
    "save_new_cookie",
    "scan_and_swallow_all_long_strings",
    "send_bili_login_qrcode_to_superusers",
    "target_group_ids",
    "target_user_ids",
    "wait_startup_check_done",
]
