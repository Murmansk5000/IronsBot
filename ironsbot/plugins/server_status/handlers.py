# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""NoneBot handlers for server status commands.

NoneBot resolves handler annotations at registration time, so these annotation
imports must stay available at runtime.
"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ironsbot.shared.plugin_system import dispatch_plugin

from .matchers import (
    admin_server_status_matcher,
    bot_restart_matcher,
    disabled_bare_admin_status_matcher,
    docker_update_matcher,
    normal_server_status_matcher,
)
from .metadata import SERVER_STATUS_PLUGIN_NAME


@normal_server_status_matcher.handle()
async def handle_normal_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="normal",
    )


@disabled_bare_admin_status_matcher.handle()
async def handle_disabled_bare_admin_status(event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=disabled_bare_admin_status_matcher,
        action="disabled_bare_admin",
    )


@admin_server_status_matcher.handle()
async def handle_admin_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="admin",
    )


@bot_restart_matcher.handle()
async def handle_bot_restart(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="restart",
    )


@docker_update_matcher.handle()
async def handle_docker_update(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="docker_update",
    )


__all__ = [
    "handle_admin_server_status",
    "handle_bot_restart",
    "handle_disabled_bare_admin_status",
    "handle_docker_update",
    "handle_normal_server_status",
]
