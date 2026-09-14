# SPDX-License-Identifier: MIT
"""Platform-neutral Bilibili command text and parsers."""

from __future__ import annotations

from ironsbot.core.commands import command_text_matches, strip_command_prefix

DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
BILI_ACCOUNT_COMMANDS = ("B站账号", "B站账户", "b站账号", "b站账户")
BILI_PUSH_MODE_COMMANDS = (
    "B站推送模式",
    "B站动态模式",
    "b站推送模式",
    "b站动态模式",
)


def is_dynamic_update_text(text: str) -> bool:
    """Recognize the required-prefix refresh command, without authorizing it."""
    command = strip_command_prefix(text)
    return command is not None and command_text_matches(
        command, DYNAMIC_UPDATE_COMMANDS
    )


def parse_bili_push_mode_command(text: str) -> tuple[str, str] | None:
    """Parse one Bilibili push-mode command without platform event state."""

    command = strip_command_prefix(text) or text.strip()
    lowered = command.lower()
    for prefix in BILI_PUSH_MODE_COMMANDS:
        if not lowered.startswith(prefix.lower()):
            continue
        rest = command[len(prefix) :].strip()
        if not rest:
            return ("", "")
        parts = rest.rsplit(maxsplit=1)
        account = parts[0].strip()
        mode_text = parts[1].strip() if len(parts) > 1 else ""
        return (account, mode_text)
    return None
