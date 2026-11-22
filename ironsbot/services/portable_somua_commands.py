# SPDX-License-Identifier: MIT
"""Shared common-Somua selection and owner-aware detail navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.semantic_requests import SemanticRequestSource
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.seer.player_shortcut_contracts import (
    player_shortcut_semantic_request,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableReply
    from ironsbot.services.seer.player_id_resolver import (
        PlayerIdResolver,
        PlayerTargetSource,
    )
    from ironsbot.services.seer.somua_models import SomuaOverviewReply


def somua_access_error(
    context: MessageInputContext,
    player_id: int,
    *,
    features: FeatureService,
    resolver: PlayerIdResolver,
    source: PlayerTargetSource,
) -> str | None:
    if features.is_message_blocked(context.message.actor, context.message.conversation):
        return "当前无法使用该查询。"
    if not features.is_feature_allowed(
        context.message.actor, context.message.conversation, "seer_player"
    ):
        return "该功能当前未对你开放。"
    return resolver.query_access_error(context.message.actor, player_id, source)


def present_somua_overview(  # noqa: PLR0913 - explicit shared operation ports
    reply: SomuaOverviewReply,
    player_id: int,
    context: MessageInputContext,
    *,
    sessions: PortableQuerySessions,
    features: FeatureService,
    resolver: PlayerIdResolver,
    source: PlayerTargetSource,
    query: Callable[[int, MessageInputContext], Awaitable[PortableReply]],
) -> OutboundMessage:
    slots = tuple(
        (index, slot)
        for index, slot in enumerate(reply.common_somua or (), 1)
        if slot.sequence
    )
    if not slots:
        return sessions.offer_view(
            context,
            OutboundMessage.from_text(
                reply.text + "\n0. 【退出】", request_succeeded=reply.complete
            ),
        )

    def access(selected: MessageInputContext) -> bool:
        actual_source = (
            source if selected.message.actor == context.message.actor else "shared_menu"
        )
        return (
            somua_access_error(
                selected,
                player_id,
                features=features,
                resolver=resolver,
                source=actual_source,
            )
            is None
        )

    async def select(
        sequence: int, selected: MessageInputContext
    ) -> PortableReply | OutboundMessage:
        if not access(selected):
            return OutboundMessage.from_text(
                "该功能当前未对你开放。", request_succeeded=False
            )
        return await query(sequence, selected)

    choices = tuple(slot.sequence for _, slot in slots)
    names = dict(reply.common_names)
    labels = tuple(
        names.get(slot.sequence) or f"常用苏摩{index}（实例 {slot.sequence}）"
        for index, slot in slots
    )
    text = (
        reply.text
        + "\n【常用苏摩】\n"
        + "\n".join(
            f"{index}. {label}" for (index, _), label in zip(slots, labels, strict=True)
        )
        + "\n0. 【退出】"
    )
    return sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=choices,
            labels=labels,
            choice_keys=tuple(str(index) for index, _ in slots),
            select=select,
            shared_select=select,
            shared_choice_indexes=frozenset(range(1, len(choices) + 1)),
            semantic_request=lambda sequence, _selected: (
                player_shortcut_semantic_request(
                    kind="somua_detail",
                    player_id=player_id,
                    sequence=sequence,
                    source=SemanticRequestSource.MENU,
                )
            ),
            access=access,
            keep_open=True,
            child=True,
            prompt=OutboundMessage.from_text(text, request_succeeded=reply.complete),
        ),
    )
