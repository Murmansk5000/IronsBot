# SPDX-License-Identifier: MIT
"""One four-skin result menu for active queries and daily private deliveries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_query_sessions import PortableMenuSpec

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWindowResult,
        LuckySkinWindowService,
    )
    from ironsbot.services.seer.pet_query import PetImageSelection, PetQueryService
    from ironsbot.services.seer.query_result import QueryChoice


async def lucky_skin_result_menu(  # noqa: PLR0913 - shared rendering dependencies
    service: LuckySkinWindowService,
    pet: PetQueryService,
    features: FeatureService,
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    actor: ActorRef | None,
    result: LuckySkinWindowResult,
) -> OutboundMessage:
    choices = service.detail_choices(result)
    message = await service.result_message(result, actor=actor)
    if not choices:
        return message

    async def select(
        choice: QueryChoice[PetImageSelection], _context: MessageInputContext
    ) -> OutboundMessage:
        selected = await pet.select_image(choice.value)
        if selected.reply is not None:
            return selected.reply.to_outbound()
        return OutboundMessage.from_text(selected.message or "❌ 皮肤详情暂时不可用。")

    return sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=choices,
            select=select,
            prompt=message,
            labels=tuple(choice.name for choice in choices),
            shareable=True,
            keep_open=True,
            access=lambda ctx: features.is_feature_allowed(
                ctx.message.actor, ctx.message.conversation, "seer_pet"
            ),
        ),
    )
