# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata, on_fullmatch
from nonebot.rule import Rule

from ironsbot.services.seer.rank_usage import build_rank_help_message
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

RANK_HELP_PLUGIN_NAME = "rank_help"

__plugin_meta__ = PluginMetadata(
    name="榜单",
    description="查看全服榜、机器人样本榜、巅峰样本榜和刻印数值榜",
    usage=build_rank_help_message(),
)

rank_help_entry = on_fullmatch(
    ("榜单", "排行榜"),
    rule=Rule(lambda event: is_event_feature_allowed(event, "rank")) & no_reply(),
    priority=get_matcher_priority("seer_rank_help", 2),
    block=True,
)


class RankHelpPlugin:
    name = RANK_HELP_PLUGIN_NAME
    feature = "rank"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:  # noqa: ARG002
        matcher = context.matcher or rank_help_entry
        await matcher.finish(build_rank_help_message())


register_plugin(RankHelpPlugin())


@rank_help_entry.handle()
async def handle_rank_help_entry(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=RANK_HELP_PLUGIN_NAME,
        event=event,
        matcher=matcher,
    )
