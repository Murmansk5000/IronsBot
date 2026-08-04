# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.runtime.commands import CommandAccess

if TYPE_CHECKING:
    from ironsbot.runtime.commands import CommandDescriptor


def ai_chat_commands(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    if not enabled:
        return ()
    return (
        *commands_from_rows(
            "ai_chat",
            "群聊",
            "ai_chat",
            (
                (
                    "ai_chat.group",
                    ("@机器人 <问题>",),
                    "向 AI 聊天提问",
                    {"access": (CommandAccess(scope="group"),)},
                ),
            ),
        ),
        *commands_from_rows(
            "ai_chat",
            "私聊",
            "ai_chat",
            (
                (
                    "ai_chat.private",
                    ("<问题>",),
                    "直接向 AI 聊天提问",
                    {"access": (CommandAccess(scope="private"),)},
                ),
            ),
        ),
    )
