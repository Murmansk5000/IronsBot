# SPDX-License-Identifier: GPL-3.0-or-later
"""Pet query matchers."""

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import (
    pet_avatar_input,
    pet_image_input,
    pet_query_input,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.pet_query
    avatar_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_pet_avatar",
            help_ids=("seer.pet.avatar",),
        ),
        rule=seer_feature_rule(group.features, "seer_pet")
        & affix_command(pet_avatar_input(group.image_command_texts))
        & explicit_command(),
        priority=group.matcher_priority("seer_pet"),
    )
    avatar_matcher.append_handler(
        make_query_handler(
            service.search_avatar,
            service.select_avatar,
            "请选择要查询头像的精灵：",
            ActionDefinition("seer_pet_avatar", "精灵头像查询"),
        )
    )
    image_matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_pet_image",
            help_ids=("seer.pet.image",),
        ),
        rule=seer_feature_rule(group.features, "seer_pet")
        & affix_command(pet_image_input(group.image_command_texts))
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
        & affix_command(pet_query_input(group.image_command_texts))
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
