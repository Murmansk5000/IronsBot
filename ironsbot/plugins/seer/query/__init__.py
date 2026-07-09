# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="赛尔号查询",
    description="按当前权限开放赛尔号查询子功能",
    usage=(
        "帮助菜单会根据当前群/私聊启用的 seer_player、seer_pet、"
        "seer_mintmark 等子功能动态显示可用指令。"
    ),
)
