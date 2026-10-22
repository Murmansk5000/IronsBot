# SPDX-License-Identifier: MIT
"""Notice wire validation and conversion to existing public event services."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.errors import OneBotActionError
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.red_packet import red_packet_group_name
from ironsbot.integrations.onebot.wire_fields import (
    OneBotInteger,  # noqa: TC001 - Pydantic field resolution
)

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.connections import OneBotConnection
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.services.messaging.poke_reply import PokeReplyService
    from ironsbot.services.messaging.red_packet import RedPacketNoticeService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.audit import TeamAuditService

logger = logging.getLogger(__name__)


class OneBotNoticeEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: OneBotInteger
    self_id: OneBotInteger
    post_type: Literal["notice"]
    notice_type: str
    sub_type: str | None = None
    group_id: OneBotInteger | None = None
    user_id: OneBotInteger | None = None
    target_id: OneBotInteger | None = None
    operator_id: OneBotInteger | None = None

    @property
    def is_poke_at_bot(self) -> bool:
        return (
            self.notice_type == "notify"
            and self.sub_type == "poke"
            and self.user_id is not None
            and self.target_id == self.self_id
        )

    @property
    def is_group_increase(self) -> bool:
        return (
            self.notice_type == "group_increase"
            and self.sub_type is not None
            and self.user_id is not None
            and self.group_id is not None
            and self.operator_id is not None
        )


def decode_notice(payload: dict[str, Any]) -> OneBotNoticeEnvelope | None:
    try:
        return OneBotNoticeEnvelope.model_validate(payload)
    except ValidationError:
        logger.warning("OneBot notice rejected: invalid envelope")
        return None


def notice_context(user_id: int, group_id: int | None) -> CommandContext:
    return CommandContext(
        onebot_actor_ref(user_id), onebot_conversation_ref(user_id, group_id=group_id)
    )


async def _group_role(
    connection: OneBotConnection, user_id: int, group_id: int | None
) -> str | None:
    if group_id is None:
        return None
    try:
        info = await connection.call_api(
            "get_group_member_info", group_id=group_id, user_id=user_id, no_cache=True
        )
    except OneBotActionError:
        return None
    role = info.get("role") if isinstance(info, Mapping) else None
    return str(role) if role is not None else None


async def poke_onebot_member(
    connection: OneBotConnection,
    user_id: int,
    group_id: int | None,
    *,
    service: PokeReplyService,
    messenger: OneBotOutboundMessenger,
) -> None:
    context = notice_context(user_id, group_id)
    await service.handle(
        context,
        partial(messenger.send_from, connection, context),
        group_role=partial(_group_role, connection, user_id, group_id),
    )


async def welcome_onebot_member(
    self_id: int,
    user_id: int,
    group_id: int,
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    if user_id == self_id:
        return
    await service.welcome(
        conversation=ConversationRef(Platform.ONEBOT, "group", str(group_id)),
        actor=ActorRef(
            Platform.ONEBOT, str(user_id), kind="member", scope_id=str(group_id)
        ),
        joined_at=datetime.now(timezone.utc),
        scheduler=scheduler,
    )


async def notify_onebot_red_packet(
    connection: OneBotConnection,
    user_id: int,
    group_id: int,
    *,
    service: RedPacketNoticeService,
) -> None:
    await service.handle(
        notice_context(user_id, group_id),
        summary="红包通知",
        conversation_name=partial(red_packet_group_name, connection, group_id),
    )
