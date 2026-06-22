# SPDX-License-Identifier: MIT
from __future__ import annotations

HELP_COMMAND_TEXT = "帮助"
DIRECT_COMMAND_HELP_HINT_TEXT = (
    f"直接发送指令就可以查询；不会用可以发送“{HELP_COMMAND_TEXT}”。"
)
HELP_HINT_TEXT = DIRECT_COMMAND_HELP_HINT_TEXT
POKE_HELP_HINT_TEXT = DIRECT_COMMAND_HELP_HINT_TEXT


def append_help_hint(message: str, *, hint: str = HELP_HINT_TEXT) -> str:
    text = message.rstrip()
    if hint in text:
        return text
    separator = "" if text.endswith(("。", "！", "？", ".", "!", "?")) else "。"
    return f"{text}{separator}{hint}"


def unsupported_feature_help_message(feature_text: str) -> str:
    return append_help_hint(f"此机器人暂不支持{feature_text}。")


__all__ = [
    "DIRECT_COMMAND_HELP_HINT_TEXT",
    "HELP_COMMAND_TEXT",
    "HELP_HINT_TEXT",
    "POKE_HELP_HINT_TEXT",
    "append_help_hint",
    "unsupported_feature_help_message",
]
