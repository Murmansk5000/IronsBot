# SPDX-License-Identifier: GPL-3.0-or-later
"""Equipment query matchers."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import EQUIP_QUERY, SUIT_QUERY, TITLE_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler

if TYPE_CHECKING:
    from ironsbot.core.affix_commands import AffixParser
    from ironsbot.services.seer.equipment import EquipmentKind


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.equipment
    commands: tuple[
        tuple[EquipmentKind, str, AffixParser, str],
        ...,
    ] = (
        (
            "suit",
            "seer_suit_query",
            SUIT_QUERY,
            "请问你想查询的套装是……",
        ),
        (
            "equip",
            "seer_equipment_query",
            EQUIP_QUERY,
            "请问你想查询的装备部件是……",
        ),
        (
            "title",
            "seer_title_query",
            TITLE_QUERY,
            "请问你想查询的称号是……",
        ),
    )
    for kind, command_id, parser, prompt_title in commands:
        matcher = group.on_message(
            policy=CommandPolicy.command(
                command_id,
                help_ids=("seer.equipment.query",),
            ),
            rule=seer_feature_rule(group.features, "seer_equipment")
            & affix_command(parser)
            & explicit_command(),
            priority=group.matcher_priority("seer_equipment"),
        )
        matcher.append_handler(
            make_query_handler(
                partial(service.search, kind),
                partial(service.select, kind),
                prompt_title,
                ActionDefinition(command_id, f"{kind}查询"),
                sessions=group.query_sessions,
            )
        )
