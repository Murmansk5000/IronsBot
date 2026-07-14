# SPDX-License-Identifier: MIT
from __future__ import annotations

HELP_COMMAND_TEXT = "帮助"
DIRECT_COMMAND_HELP_HINT_TEXT = (
    f"直接发送指令即可使用机器人功能；使用“{HELP_COMMAND_TEXT}”指令获取帮助。"
)
HELP_HINT_TEXT = DIRECT_COMMAND_HELP_HINT_TEXT
POKE_HELP_HINT_TEXT = DIRECT_COMMAND_HELP_HINT_TEXT
PET_CONFIG_UNAVAILABLE_TEXT = (
    "本机器人因无人搜集、整理、维护精灵配置图，无法开放配置查询功能。"
)


def append_help_hint(message: str, *, hint: str = HELP_HINT_TEXT) -> str:
    text = message.rstrip()
    if hint in text:
        return text
    separator = "" if text.endswith(("。", "！", "？", ".", "!", "?")) else "。"
    return f"{text}{separator}{hint}"


__all__ = [
    "DIRECT_COMMAND_HELP_HINT_TEXT",
    "HELP_COMMAND_TEXT",
    "HELP_HINT_TEXT",
    "PET_CONFIG_UNAVAILABLE_TEXT",
    "POKE_HELP_HINT_TEXT",
    "append_help_hint",
]
