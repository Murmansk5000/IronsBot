# SPDX-License-Identifier: MIT
"""OneBot event adapter for the shared pet-flip operation."""

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import member_targets_command

from ..group import SeerMatcherGroup, seer_feature_rule


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.pet_flip
    if service is None:
        return

    async def matches(event: Event) -> bool:
        return (
            isinstance(event, GroupMessageEvent)
            and message_input_context(event).text.strip().lstrip("/") == "抛精灵"
        )

    matcher = group.on_message(
        policy=CommandPolicy.command("pet_flip", help_ids=("seer.pet.flip",)),
        rule=Rule(matches)
        & seer_feature_rule(group.features, "pet_flip")
        & member_targets_command(),
    )
    matcher.append_handler(
        make_portable_query_handler(service.play, group.query_sessions)
    )
