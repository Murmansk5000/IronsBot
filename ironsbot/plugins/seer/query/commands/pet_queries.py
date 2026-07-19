# SPDX-License-Identifier: GPL-3.0-or-later
"""Pet query matchers."""

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.runtime.rules import no_reply, startswith_or_endswith

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler
from .query_rules import not_fixed_image_command, not_rank_query


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.pet_query
    image_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_image"),
        rule=seer_feature_rule(group.features, "seer_pet")
        & startswith_or_endswith(
            prefixes=("立绘", "皮肤", "查询立绘"),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=group.matcher_priority("seer_pet"),
    )
    image_matcher.append_handler(
        make_query_handler(
            service.search_image,
            service.select_image,
            "请问你想查询的立绘是……",
        )
    )

    info_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_info"),
        rule=seer_feature_rule(group.features, "seer_pet")
        & startswith_or_endswith(
            prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
            suffixes=("查询精灵信息", "魂印", "技能"),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=group.matcher_priority("seer_pet"),
    )
    info_matcher.append_handler(
        make_query_handler(
            service.search_info,
            service.select_info,
            "请问你想查询的精灵是……",
        )
    )
