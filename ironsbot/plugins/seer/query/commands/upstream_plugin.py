# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ..upstream_commands import cloth as upstream_cloth
from ..upstream_commands import effect as upstream_effect
from ..upstream_commands import mintmark as upstream_mintmark
from ..upstream_commands import peak as upstream_peak
from ..upstream_commands import type as upstream_type
from . import data_tools, upstream_pet_handlers
from .upstream_help import finish_query_help

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher

    from ironsbot.shared.plugin_system import PluginContext

UPSTREAM_QUERY_PLUGIN_NAME = "seer_upstream_queries"
UPSTREAM_QUERY_ACTION_METHODS = {
    "pet_image": "_handle_pet_image",
    "pet_info": "_handle_pet_info",
    "preview": "_handle_preview",
    "data_version": "_handle_data_version",
    "season_countdown": "_handle_season_countdown",
    "mintmark": "_handle_mintmark",
    "gem": "_handle_gem",
    "type": "_handle_type",
    "battle_effect": "_handle_battle_effect",
    "suit": "_handle_suit",
    "equip": "_handle_equip",
    "title": "_handle_title",
    "peak_pool": "_handle_peak_pool",
    "peak_expert_pool": "_handle_peak_expert_pool",
    "peak_vote": "_handle_peak_vote",
    "peak_suit": "_handle_peak_suit",
    "peak_title": "_handle_peak_title",
    "peak_pet": "_handle_peak_pet",
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

    async def _handle_pet_image(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_pet_handlers.handle_pet_image(matcher, event, context)

    async def _handle_pet_info(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_pet_handlers.handle_pet_info(matcher, event, context)

    async def _handle_preview(
        self,
        _: Matcher,
        __: Event,
        context: PluginContext,
    ) -> None:
        await data_tools.handle_preview(session=context.data["session"])

    async def _handle_data_version(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await data_tools.handle_data_version(
            matcher=matcher,
            session=context.data["session"],
        )

    async def _handle_season_countdown(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await data_tools.handle_season_countdown(
            matcher=matcher,
            event=event,
            session=context.data["session"],
        )

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

    async def _handle_type(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_type.handle_type(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            session=context.data["session"],
            type_combinations=context.data["type_combinations"],
        )

    async def _handle_battle_effect(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_effect.handle_battle_effect(
            matcher=matcher,
            event=event,
            state=context.state if context.state is not None else {},
            battle_effects=context.data["battle_effects"],
        )

    async def _handle_suit(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_cloth.handle_suit(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            suits=context.data["suits"],
        )

    async def _handle_equip(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_cloth.handle_equip(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            equips=context.data["equips"],
        )

    async def _handle_title(
        self,
        matcher: Matcher,
        event: Event,
        context: PluginContext,
    ) -> None:
        await upstream_cloth.handle_title(
            matcher=matcher,
            state=context.state if context.state is not None else {},
            event=event,
            titles=context.data["titles"],
        )

    async def _handle_peak_pool(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_pool(
            matcher=matcher,
            pools=context.data["pools"],
        )

    async def _handle_peak_expert_pool(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_expert_pool(
            matcher=matcher,
            pools=context.data["pools"],
        )

    async def _handle_peak_vote(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_vote(
            matcher=matcher,
            session=context.data["session"],
            game=context.data["game"],
        )

    async def _handle_peak_suit(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_suit(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            sessions=context.data["sessions"],
            type_tuple=context.data["type_tuple"],
            game=context.data["game"],
        )

    async def _handle_peak_title(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_title(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            sessions=context.data["sessions"],
            type_tuple=context.data["type_tuple"],
            game=context.data["game"],
        )

    async def _handle_peak_pet(
        self,
        matcher: Matcher,
        _: Event,
        context: PluginContext,
    ) -> None:
        await upstream_peak.handle_peak_pet(
            matcher=matcher,
            seerapi_session=context.data["seerapi_session"],
            command=context.data["command"],
            type_tuple=context.data["type_tuple"],
            expert_pools=context.data["expert_pools"],
            game=context.data["game"],
        )
