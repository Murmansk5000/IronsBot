# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule

from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_countermark_commands import (
    build_portable_countermark_operations,
)
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)

from ..group import SeerMatcherGroup, seer_feature_rule


def _match_command(
    event: Event,
) -> bool:
    return parse_countermark_stat_rank_command(event.get_plaintext()) is not None


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.countermark_rank
    operation = build_portable_countermark_operations(service)["seer.mintmark.rank"]
    matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_countermark_stat_rank",
            help_ids=("seer.mintmark.rank",),
        ),
        rule=seer_feature_rule(group.features, "seer_mintmark")
        & Rule(_match_command)
        & explicit_command(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    matcher.append_handler(
        bind_async(run_portable_operation, operation=operation)
    )
