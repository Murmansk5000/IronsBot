# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.rule import Rule

from ironsbot.services.seer.query_guards import is_rank_query_text
from ironsbot.services.sendpic_fixed_image import FIXED_IMAGE_COMMANDS


async def _is_not_rank_query(event: Event) -> bool:
    return not is_rank_query_text(event.get_plaintext())


not_rank_query = Rule(_is_not_rank_query)


async def _is_not_fixed_image_command(event: Event) -> bool:
    return event.get_plaintext().strip() not in FIXED_IMAGE_COMMANDS


not_fixed_image_command = Rule(_is_not_fixed_image_command)


__all__ = ["not_fixed_image_command", "not_rank_query"]
