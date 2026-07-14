# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""NoneBot handlers for server status commands.

NoneBot resolves handler annotations at registration time, so these annotation
imports must stay available at runtime.
"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ironsbot.shared.messaging import finish_event_reply

from .commands import handle_admin_status, handle_normal_status
from .matchers import (
    admin_server_status_matcher,
    bot_restart_matcher,
    disabled_bare_admin_status_matcher,
    docker_update_matcher,
    normal_server_status_matcher,
)
from .metadata import __plugin_meta__
from .restart_command import handle_restart_command


@normal_server_status_matcher.handle()
async def handle_normal_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await handle_normal_status(matcher, event)


@disabled_bare_admin_status_matcher.handle()
async def handle_disabled_bare_admin_status(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        str(__plugin_meta__.usage or "暂无详细帮助。"),
    )


@admin_server_status_matcher.handle()
async def handle_admin_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await handle_admin_status(matcher, event)


@bot_restart_matcher.handle()
async def handle_bot_restart(matcher: Matcher, event: MessageEvent) -> None:
    await handle_restart_command(matcher, event)


@docker_update_matcher.handle()
async def handle_docker_update(matcher: Matcher, event: MessageEvent) -> None:
    await handle_restart_command(matcher, event)


__all__ = [
    "handle_admin_server_status",
    "handle_bot_restart",
    "handle_disabled_bare_admin_status",
    "handle_docker_update",
    "handle_normal_server_status",
]
