# SPDX-License-Identifier: GPL-3.0-or-later
"""Equipment query matchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import EQUIP_QUERY, SUIT_QUERY, TITLE_QUERY

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.core.affix_commands import AffixParser


def install(group: SeerMatcherGroup) -> None:
    commands: tuple[
        tuple[str, AffixParser],
        ...,
    ] = (
        (
            "seer_suit_query",
            SUIT_QUERY,
        ),
        (
            "seer_equipment_query",
            EQUIP_QUERY,
        ),
        (
            "seer_title_query",
            TITLE_QUERY,
        ),
    )
    for command_id, parser in commands:
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
                group.operation("seer.equipment.query"), group.query_sessions
            )
        )
