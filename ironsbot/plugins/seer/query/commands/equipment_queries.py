# SPDX-License-Identifier: GPL-3.0-or-later
"""Equipment query matchers."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.runtime.rules import explicit_command, startswith_or_endswith
from ironsbot.runtime.semantic_requests import ActionDefinition

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import make_query_handler
from .query_rules import not_rank_query

if TYPE_CHECKING:
    from ironsbot.services.seer.equipment import EquipmentKind


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.equipment
    commands: tuple[
        tuple[EquipmentKind, str, tuple[str, ...], str, str],
        ...,
    ] = (
        (
            "suit",
            "seer_suit_query",
            ("套装", "查询套装信息"),
            "套装",
            "请问你想查询的套装是……",
        ),
        (
            "equip",
            "seer_equipment_query",
            ("部件", "查询部件信息"),
            "部件",
            "请问你想查询的装备部件是……",
        ),
        (
            "title",
            "seer_title_query",
            ("称号", "查询称号信息"),
            "称号",
            "请问你想查询的称号是……",
        ),
    )
    for kind, command_id, prefixes, suffix, prompt_title in commands:
        matcher = group.on_message(
            policy=CommandPolicy.command(
                command_id,
                help_ids=("seer.equipment.query",),
            ),
            rule=seer_feature_rule(group.features, "seer_equipment")
            & startswith_or_endswith(prefixes, suffixes=suffix)
            & not_rank_query
            & explicit_command(),
            priority=group.matcher_priority("seer_equipment"),
        )
        matcher.append_handler(
            make_query_handler(
                partial(service.search, kind),
                partial(service.select, kind),
                prompt_title,
                ActionDefinition(command_id, f"{kind}查询"),
            )
        )
