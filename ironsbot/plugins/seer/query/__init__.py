# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.plugin import PluginMetadata

from . import commands as commands

__plugin_meta__ = PluginMetadata(
    name="扩展赛尔号查询",
    description="自定义赛尔号查询入口，覆盖玩家、战队、精灵、刻印、榜单与活动常用查询",
    usage=(
        "【玩家】feature: seer_player\n"
        "米米号123456 / 查询玩家信息123456\n"
        "查到基础信息后，发送“收集”或“巅峰”查看详情。\n\n"
        "【战队】feature: seer_team\n"
        "战队123456 / 查询战队信息123456\n\n"
        "【精灵、技能、魂印、立绘、皮肤】feature: seer_pet\n"
        "精灵雷伊 / 雷伊魂印 / 圣武技能\n"
        "雷伊立绘 / 雷伊皮肤 / 皮肤雷伊\n\n"
        "【刻印、宝石、刻印榜】feature: seer_mintmark\n"
        "刻印V8 / 精灵王刻印 / 宝石绝命\n"
        "刻印攻击榜 / 六角双攻榜 / 特攻双防刻印榜\n\n"
        "【套装、部件、称号】feature: seer_equipment\n"
        "典狱套装 / 部件漫游者 / 称号神话\n\n"
        "【属性与异常】feature: seer_type\n"
        "属性圣灵 / 火战斗属性 / 属性火+战斗\n"
        "异常中毒 / 冻伤异常\n\n"
        "【巅峰相关】feature: seer_peak\n"
        "竞技池 / 专家池 / 巅峰投票\n"
        "竞技套装榜 / 狂野称号榜 / 专家段位榜\n"
        "竞技精灵月榜 / 竞技精灵总榜\n\n"
        "【群星牌】feature: seer_autocard\n"
        "群星牌布布种子 / 布布种子群星牌\n\n"
        "【榜单入口】feature: seer_rank\n"
        "榜单 / 榜单帮助 / 榜单情况 / 样本情况\n\n"
        "【数据工具】feature: seer_data\n"
        "下周预告 / 数据版本\n\n"
        "配置中 seer 是以上所有赛尔查询子功能的总别名。"
    ),
)

__all__ = ["commands"]
