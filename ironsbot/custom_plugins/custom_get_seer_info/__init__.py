# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.plugin import PluginMetadata

from . import commands as commands

__plugin_meta__ = PluginMetadata(
    name="扩展赛尔号查询",
    description="自定义米米号与战队查询，展示比原插件更多的信息",
    usage=(
        "【玩家与战队】\n"
        "米米号123456\n"
        "查询玩家信息123456\n"
        "战队123456\n"
        "查询战队信息123456\n\n"
        "回复“收集”查看玩家收集与排行详情。\n"
        "发送“榜单”查看全服榜、样本榜、巅峰榜和刻印数值榜。"
    ),
)

__all__ = ["commands"]
