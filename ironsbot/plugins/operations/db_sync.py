# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.core.commands import normalize_command_text
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import no_reply

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher

    from ironsbot.services.operations.data_sync import DataSyncService

MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
FORCE_MANUAL_SYNC_COMMANDS = ("强制更新数据", "强制数据更新")
ADMIN_COMMAND_PREFIX = "/"
NORMALIZED_MANUAL_SYNC_COMMANDS = {
    normalize_command_text(command) for command in MANUAL_SYNC_COMMANDS
}
NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS = {
    normalize_command_text(command) for command in FORCE_MANUAL_SYNC_COMMANDS
}


async def _is_manual_sync_command(event: Event) -> bool:
    text = event.get_plaintext().strip()
    if not text.startswith(ADMIN_COMMAND_PREFIX):
        return False

    command = normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return (
        command in NORMALIZED_MANUAL_SYNC_COMMANDS
        or command in NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS
    )


def _is_force_manual_sync_event(event: Event) -> bool:
    text = event.get_plaintext().strip()
    command = normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return command in NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS


def install(registry: MatcherRegistry, service: DataSyncService) -> None:
    async def handle_sync(matcher: Matcher, event: MessageEvent) -> None:
        force = _is_force_manual_sync_event(event)
        message, should_run = service.prepare_manual(force=force)
        if not should_run:
            await finish_event_reply(
                matcher,
                event,
                message,
            )
        await send_event_reply(matcher, event, message)
        await finish_event_reply(
            matcher,
            event,
            await service.run_manual(force=force),
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command("data_sync"),
        rule=Rule(_is_manual_sync_command) & no_reply(),
        permission=SUPERUSER,
        priority=registry.priority("db_sync"),
        block=True,
    )
    matcher.append_handler(handle_sync)
