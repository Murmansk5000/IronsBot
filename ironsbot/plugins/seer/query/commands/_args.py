# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.runtime.params import parse_string_arg


async def has_numeric_command_arg(state: T_State) -> bool:
    return parse_string_arg(state).strip().isdigit()


has_numeric_arg = Rule(has_numeric_command_arg)


async def parse_numeric_id(
    matcher: Matcher,
    state: T_State,
    *,
    min_value: int,
    max_value: int,
    error_message: str,
) -> int:
    raw_arg = parse_string_arg(state).strip()
    if not raw_arg.isdigit():
        await matcher.finish(error_message)

    value = int(raw_arg)
    if value < min_value or value > max_value:
        await matcher.finish(error_message)

    return value
