# SPDX-License-Identifier: GPL-3.0-or-later
"""Equipment query matchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_equipment_query_operations,
)
from ironsbot.services.seer.query_commands import EQUIP_QUERY, SUIT_QUERY, TITLE_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.core.affix_commands import AffixParser
    from ironsbot.services.seer.equipment import EquipmentKind


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.equipment
    operation = build_portable_equipment_query_operations(
        service,
        group.query_sessions,
    )["seer.equipment.query"]
    commands: tuple[tuple[EquipmentKind, str, AffixParser], ...] = (
        (
            "suit",
            "seer_suit_query",
            SUIT_QUERY,
        ),
        (
            "equip",
            "seer_equipment_query",
            EQUIP_QUERY,
        ),
        (
            "title",
            "seer_title_query",
            TITLE_QUERY,
        ),
    )
    for kind, command_id, parser in commands:
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
            make_portable_query_handler(
                operation,
                group.query_sessions,
                ActionDefinition(command_id, f"{kind}查询"),
            )
        )
