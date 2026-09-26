# SPDX-License-Identifier: MIT
"""Platform-neutral execution for public rank queries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.portable_interactions import as_portable_reply
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import (
    PortableReply,
    progress_operation_reply,
)
from ironsbot.services.seer.rank_display import parse_rank_display_limit_command
from ironsbot.services.seer.rank_list_models import (
    RANK_PAGE_OVERVIEW_COMMANDS,
    RankListPreparedReply,
    RankListSelection,
    RankPlayerCommand,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_queries import RankQueryService

    ProgressReporter = Callable[[str], Awaitable[None]]

_PUBLIC_RANK_COMMAND_IDS = (
    "rank.global_collection",
    "rank.global_peak",
    "rank.sample_collection",
    "rank.sample_peak",
)


def build_portable_rank_operations(
    service: RankQueryService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    player_query: PortableOperation,
    features: FeatureService,
) -> dict[str, PortableOperation]:
    owner = _PortableRankOperations(service, resolver, sessions, player_query, features)
    return {
        **dict.fromkeys(_PUBLIC_RANK_COMMAND_IDS, owner.query),
        "rank.display_limit": owner.set_display_limit,
    }


def build_portable_rank_admin_operations(
    service: RankAdminService,
) -> dict[str, PortableOperation]:
    """Build cache diagnostics and maintenance for authorized catalog users."""
    owner = _PortableRankAdminOperations(service)
    return {
        "rank.sample_status": owner.sample_status,
        "rank.sample_refresh": owner.sample_refresh,
        "rank.page_status": owner.page_status,
        "rank.page_refresh": owner.page_refresh,
        "rank.page_batch": owner.page_batch,
    }


@dataclass(frozen=True, slots=True)
class _PortableRankAdminOperations:
    service: RankAdminService

    async def sample_status(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(
            self.service.cache_status(context.message.conversation)
        )

    async def page_status(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        command_text = _prefixed(text)
        if command_text in RANK_PAGE_OVERVIEW_COMMANDS:
            return OutboundMessage.from_text(self.service.page_overview())
        command = parse_rank_page_cache_status_command(command_text)
        if command is None:
            msg = f"catalog accepted invalid rank status input: {text!r}"
            raise ValueError(msg)
        return OutboundMessage.from_text(self.service.page_status(command))

    async def sample_refresh(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del text

        async def refresh(progress: ProgressReporter) -> str:
            return await self.service.cache_refresh(
                actor=context.message.actor,
                progress=progress,
            )

        return await progress_operation_reply(refresh)

    async def page_refresh(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        command = parse_rank_page_cache_refresh_command(_prefixed(text))
        if command is None:
            msg = f"catalog accepted invalid rank refresh input: {text!r}"
            raise ValueError(msg)

        async def refresh(progress: ProgressReporter) -> str:
            return await self.service.page_refresh(
                command,
                actor=context.message.actor,
                progress=progress,
            )

        return await progress_operation_reply(refresh)

    async def page_batch(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        command = parse_rank_cache_batch_command(_prefixed(text))
        if command is None:
            msg = f"catalog accepted invalid rank batch input: {text!r}"
            raise ValueError(msg)

        async def cache(progress: ProgressReporter) -> str:
            return await self.service.cache_batch(
                command,
                actor=context.message.actor,
                progress=progress,
            )

        return await progress_operation_reply(cache)


def _prefixed(text: str) -> str:
    return text if text.startswith("/") else f"/{text}"


@dataclass(frozen=True, slots=True)
class _PortableRankOperations:
    service: RankQueryService
    resolver: PlayerIdResolver
    sessions: PortableQuerySessions
    player_query: PortableOperation
    features: FeatureService

    async def set_display_limit(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        command_text = text if text.startswith("/") else f"/{text}"
        limit = parse_rank_display_limit_command(command_text)
        if limit is None:
            msg = f"catalog accepted invalid rank display input: {text!r}"
            raise ValueError(msg)
        message = context.message
        return OutboundMessage.from_text(
            self.service.set_display_limit(
                conversation=message.conversation,
                actor=message.actor,
                can_manage=True,
                limit=limit,
            )
        )

    async def query(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        player_target = parse_rank_player_target_command(text)
        if context.has_member_mentions and player_target is not None:
            return await self._player(player_target.rank_key, None, context)

        listed = parse_rank_list_command(
            text,
            default_limit=self.service.default_limit(context.message.conversation),
        )
        if listed is not None:
            result = await self.service.prepare_list(
                listed,
                actor=context.message.actor,
                conversation=context.message.conversation,
            )
            return self._rank_menu(result, context)

        scored = parse_rank_score_command(text)
        if scored is not None:
            result = await self.service.prepare_score(
                scored,
                actor=context.message.actor,
                conversation=context.message.conversation,
            )
            return self._rank_menu(result, context)

        if player_target is not None:
            return await self._player(
                player_target.rank_key,
                player_target.player_reference,
                context,
            )

        msg = f"catalog accepted input that its rank parser rejected: {text!r}"
        raise ValueError(msg)

    def _rank_menu(
        self,
        result: RankListPreparedReply,
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        if not result.selections:
            return OutboundMessage.from_text(result.message)

        async def select(
            choice: RankListSelection,
            selection_context: MessageInputContext,
        ) -> OutboundMessage | PortableReply:
            reply = await self.player_query(
                f"米米号{choice.player_id}",
                replace(selection_context, offer_player_binding=False),
            )
            if reply is None:
                msg = "player query operation returned no reply"
                raise ValueError(msg)
            return as_portable_reply(reply)

        def semantic_request(
            choice: RankListSelection,
            _selection_context: MessageInputContext,
        ) -> SemanticRequest:
            return SemanticRequest(
                action=ActionDefinition(
                    "seer.player.info",
                    "米米号基础资料",
                    cooldown_key="seer_player",
                ),
                target=SemanticTarget(
                    key=str(choice.player_id),
                    display=f"米米号 {choice.player_id}",
                ),
                source=SemanticRequestSource.MENU,
            )

        prompt = OutboundMessage.from_text(
            f"{result.message}\n\n发送榜单中的名次查询对应玩家，发送 0 退出。"
        )
        return PortableReply(
            self.sessions.offer_menu(
                context,
                PortableMenuSpec(
                    choices=result.selections,
                    choice_keys=tuple(str(item.rank) for item in result.selections),
                    labels=tuple(
                        f"{item.rank}. {item.nick}（{item.player_id}）"
                        for item in result.selections
                    ),
                    select=select,
                    prompt=prompt,
                    shareable=True,
                    can_select=lambda _choice, responder: (
                        self.features.is_feature_allowed(
                            responder.message.actor,
                            responder.message.conversation,
                            "seer_player",
                        )
                    ),
                    semantic_request=semantic_request,
                    invalid_choice_message=(
                        "序号无效，请输入榜单中显示的名次，或输入 0 退出。"
                    ),
                    claim_unknown_numeric=False,
                    exit_message="已退出榜单玩家查询。",
                ),
            )
        )

    async def _player(
        self,
        rank_key: str,
        reference: str | None,
        context: MessageInputContext,
    ) -> PortableReply:
        resolution = self.resolver.resolve(
            context,
            reference,
            allow_default_binding=False,
        )
        if resolution.error is not None:
            return PortableReply(OutboundMessage.from_text(resolution.error))
        if resolution.player_id is None:
            return PortableReply(
                OutboundMessage.from_text(
                    "请填写米米号、已开放的玩家别名，或直接 @ 一名已绑定成员。"
                )
            )
        result = await self.service.prepare_player(
            RankPlayerCommand(rank_key, resolution.player_id),
            actor=context.message.actor,
            conversation=context.message.conversation,
        )
        return PortableReply(
            OutboundMessage.from_text(result.message),
            on_delivered=result.delivered,
        )
