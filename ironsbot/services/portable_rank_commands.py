# SPDX-License-Identifier: MIT
"""Platform-neutral execution for public rank queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.rank_list_models import RankPlayerCommand
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_list_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
)

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.rank_queries import RankQueryService

_PUBLIC_RANK_COMMAND_IDS = (
    "rank.global_collection",
    "rank.global_peak",
    "rank.sample_collection",
    "rank.sample_peak",
)


def build_portable_rank_operations(
    service: RankQueryService,
    resolver: PlayerIdResolver,
) -> dict[str, PortableOperation]:
    owner = _PortableRankOperations(service, resolver)
    return dict.fromkeys(_PUBLIC_RANK_COMMAND_IDS, owner.query)


@dataclass(frozen=True, slots=True)
class _PortableRankOperations:
    service: RankQueryService
    resolver: PlayerIdResolver

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
            result = await self.service.list(
                listed,
                actor=context.message.actor,
                conversation=context.message.conversation,
            )
            return OutboundMessage.from_text(result)

        scored = parse_rank_score_command(text)
        if scored is not None:
            result = await self.service.score(
                scored,
                actor=context.message.actor,
                conversation=context.message.conversation,
            )
            return OutboundMessage.from_text(result)

        if player_target is not None:
            return await self._player(
                player_target.rank_key,
                player_target.player_reference,
                context,
            )

        msg = f"catalog accepted input that its rank parser rejected: {text!r}"
        raise ValueError(msg)

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
