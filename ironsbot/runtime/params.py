# SPDX-License-Identifier: MIT

from nonebot.consts import CMD_ARG_KEY, PREFIX_KEY
from nonebot.typing import T_State

from .rules import BOT_COMMAND_ARG_KEY


def parse_string_arg(state: T_State) -> str:
    """统一参数提取，兼容 on_command 和 on_message + startswith_or_endswith 规则。"""
    if (arg := state.get(BOT_COMMAND_ARG_KEY, "")) and (stripped := arg.strip()):
        return stripped

    if (
        (prefix := state.get(PREFIX_KEY))
        and (cmd_arg := prefix.get(CMD_ARG_KEY)) is not None
        and (stripped := cmd_arg.extract_plain_text().strip())
    ):
        return stripped

    return ""
