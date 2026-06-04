# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.plugin import PluginMetadata, on_fullmatch

from ironsbot.custom_plugins.custom_get_seer_info.commands.rank_usage import (
    build_rank_help_message,
)
from ironsbot.utils.rule import no_reply

__plugin_meta__ = PluginMetadata(
    name="榜单",
    description="查看全服榜、机器人样本榜、巅峰样本榜和刻印数值榜",
    usage=build_rank_help_message(),
)

rank_help_entry = on_fullmatch(
    ("榜单", "排行榜"),
    rule=no_reply(),
    priority=2,
    block=True,
)


@rank_help_entry.handle()
async def handle_rank_help_entry() -> None:
    await rank_help_entry.finish(build_rank_help_message())
