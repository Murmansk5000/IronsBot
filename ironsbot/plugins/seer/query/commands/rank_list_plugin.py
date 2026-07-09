# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.shared.plugin_system import PluginContext, register_plugin

from . import (
    rank_list_cache_handlers,
    rank_list_display_handlers,
    rank_list_query_handlers,
)
from .rank_list_context import RANK_LIST_PLUGIN_NAME

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    RankListHandler = Callable[[Matcher, MessageEvent, T_State], Awaitable[None]]


RANK_LIST_ACTION_HANDLERS: dict[str, RankListHandler] = {
    "help": rank_list_query_handlers.handle_help,
    "list": rank_list_query_handlers.handle_list,
    "score": rank_list_query_handlers.handle_score,
    "cache_batch": rank_list_cache_handlers.handle_cache_batch,
    "page_cache_status": rank_list_cache_handlers.handle_page_cache_status,
    "page_cache_overview": rank_list_cache_handlers.handle_page_cache_overview,
    "page_cache_refresh": rank_list_cache_handlers.handle_page_cache_refresh,
    "cache_status": rank_list_cache_handlers.handle_cache_status,
    "cache_refresh": rank_list_cache_handlers.handle_cache_refresh,
    "display_limit": rank_list_display_handlers.handle_display_limit,
}


class RankListPlugin:
    name = RANK_LIST_PLUGIN_NAME
    feature = "seer_rank"
    enabled = True

    async def handle(
        self,
        event: MessageEvent,
        context: PluginContext,
    ) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        handler = RANK_LIST_ACTION_HANDLERS.get(context.action or "")
        if handler is None:
            return

        state = context.state if context.state is not None else {}
        await handler(matcher, event, state)


register_plugin(RankListPlugin())
