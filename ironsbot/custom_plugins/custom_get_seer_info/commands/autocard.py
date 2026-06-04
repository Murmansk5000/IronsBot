# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.custom_plugins.message_actions import command_text_matches
from ironsbot.utils.rule import no_reply

from ..group import matcher_group

AUTOCARD_COMMANDS = ("群星牌",)


def format_autocard_public_info() -> str:
    lines = [
        "🃏【群星牌公共资料】",
        "当前可从公开配置获取：",
        "卡牌：273 张，含名称、属性、等级、费用、基础攻血、效果文本",
        "赛尔角色：31 个，含生命值、技能名称、技能描述",
        "属性：草、水、火、飞行、电、地面、无",
        "商店：6 个等级，含升级花费、刷牌概率、奖励卡",
        "阵容推荐：5 组分类、20 条推荐卡组",
        "",
        "示例卡牌：加尔鲁特、海神·波塞冬、炽凰·朱雀、天尊·白虎、北冥·玄武",
        "示例角色：破界者、深海调查员、烈焰队队员、船长·罗杰、博士·派特",
        "",
        "目前这些是公共配置，不包含某个米米号的个人积分、胜率、常用卡、历史对局。",
    ]
    return "\n".join(lines)


async def _is_autocard_public_query(event: Event) -> bool:
    return command_text_matches(event.get_plaintext(), AUTOCARD_COMMANDS)


autocard_public_matcher = matcher_group.on_message(
    rule=Rule(_is_autocard_public_query) & no_reply(),
)


@autocard_public_matcher.handle()
async def handle_autocard_public(matcher: Matcher) -> None:
    await matcher.finish(format_autocard_public_info())
