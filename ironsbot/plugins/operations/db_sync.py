# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.commands import normalize_command_text
from ironsbot.runtime.conversations import enter_event_reply_conversation
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command

if TYPE_CHECKING:
    from ironsbot.services.operations.data_sync import DataSyncService

MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
FORCE_MANUAL_SYNC_COMMANDS = ("强制更新数据", "强制数据更新")
ADMIN_COMMAND_PREFIX = "/"
DATA_SYNC_FORCE_STATE_KEY = "data_sync_force"
DATA_SYNC_ACTION_NAMESPACE = "data_sync_action"
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
        message, should_run = await service.prepare_manual(force=force)
        if not should_run:
            await finish_event_reply(matcher, event, message)
            return
        matcher.state[DATA_SYNC_FORCE_STATE_KEY] = force
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DATA_SYNC_ACTION_NAMESPACE,
            handlers=[bind_async(handle_sync_action, service=service)],
            reply_check=lambda reply: _is_manual_action_reply(reply, service),
            prompt=message,
        )

    async def handle_sync_action(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
        *,
        service: DataSyncService,
    ) -> None:
        choice = event.get_plaintext().strip()
        if choice == "0":
            await finish_event_reply(matcher, event, "已取消更新。")
            return
        force = bool(state.get(DATA_SYNC_FORCE_STATE_KEY, False))
        action = service.manual_action_for_choice(choice, force=force)
        if action is None:
            await finish_event_reply(
                matcher,
                event,
                "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
            )
            return
        await finish_event_reply(
            matcher,
            event,
            await service.run_manual(action=action, force=force),
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            "data_sync",
            help_ids=("db_sync.update", "db_sync.force_update"),
        ),
        rule=Rule(_is_manual_sync_command) & explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("db_sync"),
        block=True,
    )
    matcher.append_handler(handle_sync)


def _is_manual_action_reply(event: MessageEvent, service: DataSyncService) -> bool:
    choice = event.get_plaintext().strip()
    return choice == "0" or (
        service.manual_action_for_choice(choice, force=False) is not None
    )
