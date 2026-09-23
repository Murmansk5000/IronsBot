# SPDX-License-Identifier: MIT

from nonebot import require

require("nonebot_plugin_saa")
require("ironsbot.plugins.seer_data")

from nonebot.plugin import PluginMetadata

from . import pet_flip as pet_flip

usage = """😋 娱乐功能插件
命令：
  抛精灵 <@用户1> <@用户2>  — 为两名用户随机召唤精灵进行属性克制对决，属性克制系数高的一方获胜，系数相同时序号大的一方获胜"""

__plugin_meta__ = PluginMetadata(
    name="娱乐功能",
    description="一些好玩的命令",
    usage=usage,
)
