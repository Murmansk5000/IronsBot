# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.plugin import PluginMetadata

from .config import Config

NORMAL_SERVER_STATUS_COMMAND = "开服了吗"
DISABLED_BARE_ADMIN_COMMAND = "开服查询"
ADMIN_SERVER_STATUS_COMMAND = "/开服查询"
BOT_RESTART_COMMANDS = ("/机器人重启", "/重启机器人")
DOCKER_UPDATE_COMMANDS = ("/更新镜像", "/更新Docker", "/更新docker")
SERVER_STATUS_PLUGIN_NAME = "server_status"

__plugin_meta__ = PluginMetadata(
    name="开服查询",
    description="查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服",
    usage="""命令：
  开服了吗 — 普通用户查询当前是否仍有维护公告
  /开服查询 — 超级管理员查询，并在无头未登录时尝试重连
  /机器人重启 / /重启机器人 — 超级管理员重启机器人进程
  /更新镜像 / /更新Docker — 同义命令，进入同一套重启流程；
    是否检查镜像由 runtime.docker_update.check_on_restart 控制

说明：
  裸的“开服查询”已停用，避免和管理员命令混淆。
  无头客户端已登录游戏服务器时判定为已开服；公告只作为维护信息摘要。
  无头客户端未登录时，结合公告和登录状态提示可能原因。
  如果 runtime.server_status.broadcast=true，查询结果判断为已开服时会向
  Broadcast targets use FEATURE_GROUP_POLICY / FEATURE_USER_POLICY
  feature: server_status_push.
  配置的目标广播。""",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

__all__ = [
    "ADMIN_SERVER_STATUS_COMMAND",
    "BOT_RESTART_COMMANDS",
    "DISABLED_BARE_ADMIN_COMMAND",
    "DOCKER_UPDATE_COMMANDS",
    "NORMAL_SERVER_STATUS_COMMAND",
    "SERVER_STATUS_PLUGIN_NAME",
    "__plugin_meta__",
]
