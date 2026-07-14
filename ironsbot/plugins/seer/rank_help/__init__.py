# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata, on_fullmatch
from nonebot.rule import Rule

from ironsbot.services.seer.rank_usage import (
    RANK_HELP_ENTRY_COMMANDS,
    build_rank_help_message,
)
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.utils.rule import no_reply

__plugin_meta__ = PluginMetadata(
    name="榜单",
    description="查看全服榜、机器人样本榜、巅峰样本榜和刻印数值榜",
    usage=build_rank_help_message(),
)

rank_help_entry = on_fullmatch(
    RANK_HELP_ENTRY_COMMANDS,
    rule=Rule(lambda event: is_event_feature_allowed(event, "seer_rank")) & no_reply(),
    priority=get_matcher_priority("seer_rank_help", 2),
    block=True,
)


@rank_help_entry.handle()
async def handle_rank_help_entry(matcher: Matcher) -> None:
    await matcher.finish(build_rank_help_message())
