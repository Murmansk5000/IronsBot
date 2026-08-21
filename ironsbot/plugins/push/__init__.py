# SPDX-License-Identifier: MIT
from nonebot import require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_saa")
require("nonebot_plugin_localstore")

from nonebot_plugin_saa import enable_auto_select_bot

from .config import Config

enable_auto_select_bot()

from . import commands as commands
from . import service as service

# 🧩 其他插件接入：
#   在插件中 require("ironsbot.plugins.push") 后，可调用
#   register_topic() 注册主题、send_to_topic()/send_to_targets() 主动推送，
#   配合定时任务（Schedule + provider）可实现定时推送。

usage = """🤖 消息推送中心
提供主动消息推送基础设施：主题（Topic）注册、订阅管理与定时/编程推送。
订阅关系与推送历史持久化于本地 SQLite，机器人重启不丢失。

📥 用户命令：
  订阅<主题ID> — 订阅主题（当前群/私聊）
  > 订阅公告
  退订<主题ID> — 退订主题
  > 退订公告
  我的订阅 — 查看当前会话已订阅的主题
  主题列表 — 查看全部推送主题

🔧 管理命令（仅超级用户）：
  推送新建 <ID> <名称> [描述] — 创建主题
  推送删除 <ID> — 删除主题及其订阅（代码注册的主题不可删除，仅可停用）
  推送启用 <ID> / 推送停用 <ID> — 启用/停用主题
  推送订阅者 <ID> — 查看某主题的订阅者
  推送 <ID> <内容> — 向某主题的全部订阅者推送消息
  推送直发 <群号> <内容> — 直接向指定群推送（测试/应急）"""

__plugin_meta__ = PluginMetadata(
    name="消息推送中心",
    description="通用消息推送插件：主题注册、订阅管理、定时/编程推送",
    usage=usage,
    config=Config,
    supported_adapters={"~onebot.v11"},
)
