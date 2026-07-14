# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ..upstream_commands import mintmark as upstream_mintmark
from .upstream_help import finish_query_help

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher

    from ironsbot.shared.plugin_system import PluginContext

UPSTREAM_QUERY_PLUGIN_NAME = "seer_upstream_queries"
UPSTREAM_QUERY_ACTION_METHODS = {
    "mintmark": "_handle_mintmark",
    "gem": "_handle_gem",
}


class UpstreamQueryPlugin:
    name = UPSTREAM_QUERY_PLUGIN_NAME
    feature = "seer"
    enabled = True

    async def handle(self, event: Event, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        method_name = UPSTREAM_QUERY_ACTION_METHODS.get(context.action or "")
        if method_name is None:
            return

        await getattr(self, method_name)(matcher, event, context)

    async def _handle_mintmark(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        if not str(context.data.get("arg", "")).strip():
            await finish_query_help(matcher, event, "mintmark")

        await upstream_mintmark.handle_mintmark(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            mintmarks=context.data["mintmarks"],
            classes=context.data["classes"],
        )

    async def _handle_gem(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        if not str(context.data.get("arg", "")).strip():
            await finish_query_help(matcher, event, "gem")

        await upstream_mintmark.handle_gem(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            categories=context.data["categories"],
        )
