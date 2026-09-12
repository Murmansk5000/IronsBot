# SPDX-License-Identifier: MIT

from nonebot.consts import CMD_ARG_KEY, PREFIX_KEY
from nonebot.typing import T_State

from .rules import BOT_COMMAND_ARG_KEY


def parse_string_arg(state: T_State) -> str:
    """Extract arguments from on_command or a domain affix parser's state."""
    if (arg := state.get(BOT_COMMAND_ARG_KEY, "")) and (stripped := arg.strip()):
        return stripped

    if (
        (prefix := state.get(PREFIX_KEY))
        and (cmd_arg := prefix.get(CMD_ARG_KEY)) is not None
        and (stripped := cmd_arg.extract_plain_text().strip())
    ):
        return stripped

    return ""
