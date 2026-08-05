# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Container

from nonebot.adapters import Event
from nonebot.rule import Rule

from ironsbot.core.commands import normalize_command_text
from ironsbot.services.seer.query_guards import is_rank_query_text


async def _is_not_rank_query(event: Event) -> bool:
    return not is_rank_query_text(event.get_plaintext())


not_rank_query = Rule(_is_not_rank_query)


def not_exact_command(commands: Container[str]) -> Rule:
    """Exclude a higher-priority command's exact registered spellings."""

    async def _is_not_exact_command(event: Event) -> bool:
        return normalize_command_text(event.get_plaintext()) not in commands

    return Rule(_is_not_exact_command)
