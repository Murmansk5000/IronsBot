# SPDX-License-Identifier: GPL-3.0-or-later
"""Pet query matchers."""

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.runtime.rules import explicit_command, startswith_or_endswith
from ironsbot.runtime.semantic_requests import ActionDefinition

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler
from .query_rules import not_fixed_image_command, not_rank_query


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.pet_query
    avatar_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_avatar", help_ids=("seer.pet.avatar",)),
        rule=seer_feature_rule(group.features, "seer_pet")
        & startswith_or_endswith(prefixes=("头像",), suffixes=("头像",))
        & not_fixed_image_command
        & explicit_command(),
        priority=group.matcher_priority("seer_pet"),
    )
    avatar_matcher.append_handler(
        make_query_handler(
            service.search_avatar,
            service.select_avatar,
            "选择要查询头像的精灵：",
            ActionDefinition("seer_pet_avatar", "精灵头像查询"),
        )
    )
    image_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_pet_image",
            help_ids=("seer.pet.image",),
        ),
        rule=seer_feature_rule(group.features, "seer_pet")
        & startswith_or_endswith(
            prefixes=("立绘", "皮肤", "查询立绘"),
        )
        & not_rank_query
        & not_fixed_image_command
        & explicit_command(),
        priority=group.matcher_priority("seer_pet"),
    )
    image_matcher.append_handler(
        make_query_handler(
            service.search_image,
            service.select_image,
            "请问你想查询的立绘是……",
            ActionDefinition("seer_pet_image", "精灵立绘查询"),
        )
    )

    info_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_pet_info",
            help_ids=("seer.pet.query",),
        ),
        rule=seer_feature_rule(group.features, "seer_pet")
        & startswith_or_endswith(
            prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
            suffixes=("查询精灵信息", "魂印", "技能"),
        )
        & not_rank_query
        & not_fixed_image_command
        & explicit_command(),
        priority=group.matcher_priority("seer_pet"),
    )
    info_matcher.append_handler(
        make_query_handler(
            service.search_info,
            service.select_info,
            "请问你想查询的精灵是……",
            ActionDefinition("seer_pet_info", "精灵信息查询"),
        )
    )
