# SPDX-License-Identifier: MIT

NORMAL_SERVER_STATUS_COMMAND = "开服了吗"
DISABLED_BARE_ADMIN_COMMAND = "开服查询"
ADMIN_SERVER_STATUS_COMMAND = "/开服查询"
BOT_RESTART_COMMANDS = ("/机器人重启", "/重启机器人")
DOCKER_UPDATE_COMMANDS = ("/更新镜像", "/更新Docker", "/更新docker")

SERVER_STATUS_USAGE = """命令：
  开服了吗 — 普通用户查询当前是否仍有维护公告
  /开服查询 — 超级管理员查询，并在无头未登录时尝试重连
  /机器人重启 / /重启机器人 — 超级管理员重启机器人进程
  /更新镜像 / /更新Docker — 同义命令，进入同一套重启流程；
    是否检查镜像由 operations.docker_update.check_on_restart 控制

说明：
  裸的“开服查询”已停用，避免和管理员命令混淆。
  无头客户端已登录游戏服务器时判定为已开服；公告只作为维护信息摘要。
  无头客户端未登录时，结合公告和登录状态提示可能原因。
  开服广播只发送到配置了 server_status_push 的目标。"""

__all__ = [
    "ADMIN_SERVER_STATUS_COMMAND",
    "BOT_RESTART_COMMANDS",
    "DISABLED_BARE_ADMIN_COMMAND",
    "DOCKER_UPDATE_COMMANDS",
    "NORMAL_SERVER_STATUS_COMMAND",
    "SERVER_STATUS_USAGE",
]
