# SPDX-License-Identifier: MIT
from nonebot import on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.integrations.db_sync import service
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.text import normalize_command_text
from ironsbot.utils.rule import no_reply

from .manual import ManualSyncContext, handle_manual_sync

MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
ADMIN_COMMAND_PREFIX = "/"
NORMALIZED_MANUAL_SYNC_COMMANDS = {
    normalize_command_text(command) for command in MANUAL_SYNC_COMMANDS
}


async def _is_manual_sync_command(event: Event) -> bool:
    text = event.get_plaintext().strip()
    if not text.startswith(ADMIN_COMMAND_PREFIX):
        return False

    command = normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return command in NORMALIZED_MANUAL_SYNC_COMMANDS


manual_sync_matcher = on_message(
    rule=Rule(_is_manual_sync_command) & no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("db_sync", 5),
    block=True,
)


@manual_sync_matcher.handle()
async def _handle_manual_sync(matcher: Matcher, event: MessageEvent) -> None:
    await handle_manual_sync(
        matcher,
        event,
        context=ManualSyncContext(
            registered_syncs=service._registered_syncs,
            last_sync_statuses=service._last_sync_statuses,
            default_sync_status=service._SyncStatus(ok=True),
            is_sync_running=service.is_sync_running,
            remote_build_names=service._remote_build_names,
            run_sync_all_databases=service.run_sync_all_databases,
            format_sync_statuses=service._format_sync_statuses,
            format_remote_build_failures=service._format_remote_build_failures,
        ),
    )
