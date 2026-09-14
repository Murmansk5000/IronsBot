# SPDX-License-Identifier: GPL-3.0-or-later
"""Pet query matchers."""

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_pet_query_operations,
)
from ironsbot.services.seer.query_commands import pet_image_input, pet_query_input

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.pet_query
    operations = build_portable_pet_query_operations(
        service,
        group.query_sessions,
        image_command_texts=group.image_command_texts,
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
        make_portable_query_handler(
            operations["seer.pet.image"],
            group.query_sessions,
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
        make_portable_query_handler(
            operations["seer.pet.query"],
            group.query_sessions,
            ActionDefinition("seer_pet_info", "精灵信息查询"),
        )
    )
