# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""NoneBot handlers for server status commands.

NoneBot resolves handler annotations at registration time, so these annotation
imports must stay available at runtime.
"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

from .command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DISABLED_BARE_ADMIN_COMMAND,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
    SERVER_STATUS_USAGE,
)
from .commands import handle_admin_status, handle_normal_status
from .restart_command import handle_restart_command


async def handle_normal_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await handle_normal_status(matcher, event)


async def handle_disabled_bare_admin_status(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        SERVER_STATUS_USAGE,
    )


async def handle_admin_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await handle_admin_status(matcher, event)


async def handle_bot_restart(matcher: Matcher, event: MessageEvent) -> None:
    await handle_restart_command(matcher, event)


async def handle_docker_update(matcher: Matcher, event: MessageEvent) -> None:
    await handle_restart_command(matcher, event)


def install(registry: MatcherRegistry) -> None:
    normal_matcher = registry.on_fullmatch(
        NORMAL_SERVER_STATUS_COMMAND,
        policy=CommandPolicy.command("server_status_query"),
        rule=no_reply(),
        priority=get_matcher_priority("server_status", 0),
        block=True,
    )
    normal_matcher.append_handler(handle_normal_server_status)

    disabled_matcher = registry.on_fullmatch(
        DISABLED_BARE_ADMIN_COMMAND,
        policy=CommandPolicy.command("server_status_query"),
        rule=no_reply(),
        priority=get_matcher_priority("server_status", 0),
        block=True,
    )
    disabled_matcher.append_handler(handle_disabled_bare_admin_status)

    admin_matcher = registry.on_fullmatch(
        ADMIN_SERVER_STATUS_COMMAND,
        policy=CommandPolicy.command("server_status_admin"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=get_matcher_priority("server_status_admin", 1),
        block=True,
    )
    admin_matcher.append_handler(handle_admin_server_status)

    restart_matcher = registry.on_fullmatch(
        BOT_RESTART_COMMANDS,
        policy=CommandPolicy.command("bot_restart"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=get_matcher_priority("server_status_admin", 1),
        block=True,
    )
    restart_matcher.append_handler(handle_bot_restart)

    update_matcher = registry.on_fullmatch(
        DOCKER_UPDATE_COMMANDS,
        policy=CommandPolicy.command("bot_restart"),
        rule=no_reply(),
        permission=SUPERUSER,
        priority=get_matcher_priority("server_status_admin", 1),
        block=True,
    )
    update_matcher.append_handler(handle_docker_update)


__all__ = [
    "handle_admin_server_status",
    "handle_bot_restart",
    "handle_disabled_bare_admin_status",
    "handle_docker_update",
    "handle_normal_server_status",
]
