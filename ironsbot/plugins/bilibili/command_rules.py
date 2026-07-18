# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.commands import command_text_matches, strip_command_prefix
from ironsbot.services.bilibili.permissions import (
    is_dynamic_query_allowed,
    is_dynamic_update_allowed,
)
from ironsbot.shared.features import is_event_feature_allowed

from .account_commands import (
    BILI_PUSH_MODE_ACCOUNT_KEY,
    BILI_PUSH_MODE_RAW_KEY,
)

DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
DYNAMIC_SELECT_COMMANDS = tuple(str(number) for number in range(1, 11))
BILI_ACCOUNT_COMMANDS = ("B站账号", "B站账户", "b站账号", "b站账户")
BILI_PUSH_MODE_COMMANDS = ("B站推送模式", "B站动态模式", "b站推送模式", "b站动态模式")


async def is_dynamic_menu_command(event: MessageEvent) -> bool:
    if not is_dynamic_query_allowed(event):
        return False

    return command_text_matches(
        event.get_plaintext(),
        DYNAMIC_MENU_COMMANDS,
    )


async def is_update_dynamic_command(event: MessageEvent) -> bool:
    command = strip_command_prefix(event.get_plaintext())
    if command is None:
        return False

    if not command_text_matches(
        command,
        DYNAMIC_UPDATE_COMMANDS,
    ):
        return False

    return is_dynamic_update_allowed(event)


async def is_bili_account_command(event: MessageEvent) -> bool:
    if not (
        is_dynamic_query_allowed(event) or is_event_feature_allowed(event, "bili_push")
    ):
        return False

    return command_text_matches(event.get_plaintext(), BILI_ACCOUNT_COMMANDS)


def parse_bili_push_mode_command(text: str) -> tuple[str, str] | None:
    command = strip_command_prefix(text)
    if command is None:
        command = text.strip()

    lowered = command.lower()
    for prefix in BILI_PUSH_MODE_COMMANDS:
        if not lowered.startswith(prefix.lower()):
            continue
        rest = command[len(prefix) :].strip()
        if not rest:
            return ("", "")

        parts = rest.split(maxsplit=1)
        account = parts[0].strip()
        mode_text = parts[1].strip() if len(parts) > 1 else ""
        return (account, mode_text)

    return None


async def is_bili_push_mode_command(
    event: MessageEvent,
    state: T_State,
) -> bool:
    parsed = parse_bili_push_mode_command(event.get_plaintext())
    if parsed is None:
        return False

    account, raw_mode = parsed
    state[BILI_PUSH_MODE_ACCOUNT_KEY] = account
    state[BILI_PUSH_MODE_RAW_KEY] = raw_mode
    return True


def is_dynamic_select_reply(event: MessageEvent) -> bool:
    return command_text_matches(event.get_plaintext(), DYNAMIC_SELECT_COMMANDS)
