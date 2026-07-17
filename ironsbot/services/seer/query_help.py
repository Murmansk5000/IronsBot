# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Final

SEER_QUERY_HELP_MESSAGES: Final[dict[str, str]] = {
    "autocard": "\n".join(
        (
            "🃏【群星牌查询】",
            "发送“群星牌+名字”或“名字+群星牌”查询卡牌/赛尔角色资料。",
            "示例：群星牌布布种子、群星牌卡98、布布种子群星牌",
            "发送“群星牌榜”查看排行榜；发送“群星牌+米米号”查看玩家排名。",
        )
    ),
    "pet": "\n".join(
        (
            "🔎【精灵查询】",
            "发送“精灵+名字”查询精灵信息，也可以查询技能或魂印。",
            "示例：精灵谱尼、谱尼技能、谱尼魂印",
        )
    ),
    "skin": "\n".join(
        (
            "🖼️【皮肤/立绘查询】",
            "发送“皮肤+名字”或“立绘+名字”查询精灵皮肤/立绘。",
            "示例：皮肤库贝萨、立绘伽玛、金榜灵童皮肤",
        )
    ),
    "mintmark": "\n".join(
        (
            "💮【刻印查询】",
            "发送“刻印+名字”查询刻印，或发送“系列/类型+刻印”定位刻印。",
            "示例：刻印圣战之无限、刻印九霄盾、刻印十年、V10物速",
        )
    ),
    "gem": "\n".join(
        (
            "💎【宝石查询】",
            "发送“宝石+名字”查询宝石资料。",
            "示例：宝石强攻、强攻宝石",
        )
    ),
}


def seer_query_help_message(kind: str) -> str:
    return SEER_QUERY_HELP_MESSAGES[kind]


__all__ = ["SEER_QUERY_HELP_MESSAGES", "seer_query_help_message"]
