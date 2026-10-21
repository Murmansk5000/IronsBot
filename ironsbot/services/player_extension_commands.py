# SPDX-License-Identifier: MIT
"""Shared execution of contributed player-detail actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.authorization import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.player_detail_actions import PlayerDetailActionRequest
from ironsbot.core.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.operations.request_feedback import request_feedback_scope
from ironsbot.services.player_binding_confirmation import confirm_shortcut_binding
from ironsbot.services.player_reference_selection import select_player_target
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply
from ironsbot.services.seer.player_detail_extensions import (
    extension_action_allowed,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    player_request_admission_message,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, ProgressReporter
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_service import PlayerService


async def query_player_extension(
    action: PlayerDetailExtensionAction,
    player_id: int,
    context: MessageInputContext,
    features: FeatureService,
    sessions: PortableQuerySessions | None = None,
) -> PortableReply:
    message = context.message
    if not extension_action_allowed(action, context, features):
        return PortableReply(
            OutboundMessage.from_text("该操作当前未对你开放。", request_succeeded=False)
        )

    async def execute(report: ProgressReporter) -> OutboundMessage:
        async def send_status(label: str, *, queued: bool) -> None:
            await report(player_request_admission_message(label, queued=queued))

        with request_feedback_scope(action.action.label, send_status):
            result = await action.query(
                PlayerDetailActionRequest(
                    player_id=player_id,
                    actor=message.actor,
                    conversation=message.conversation,
                    can_manage=(
                        message.group_role in GROUP_MANAGER_ROLES
                        or features.is_actor_superuser(message.actor)
                    ),
                ),
            )
        return (
            action.present(result, context, sessions)
            if action.present is not None and sessions is not None
            else result.to_outbound()
        )

    if sessions is None:
        return await progress_operation_reply(execute)
    return await sessions.interactions.execute_request(
        SemanticRequest(
            action.action,
            SemanticTarget(str(player_id), f"米米号 {player_id}"),
            SemanticRequestSource.EXTENSION,
        ),
        context,
        lambda: progress_operation_reply(execute),
    )


def build_player_extension_operation(
    extensions: PlayerDetailExtensionRegistry,
    resolver: PlayerIdResolver,
    features: FeatureService,
    sessions: PortableQuerySessions,
    player_service: PlayerService | None = None,
) -> PortableOperation:
    async def execute(text: str, context: MessageInputContext) -> PortableReply | None:
        parsed = extensions.resolve_direct_command(text)
        if parsed is None:
            msg = "player extension operation received an unrecognized command"
            raise ValueError(msg)
        action, reference = parsed
        if not extension_action_allowed(action, context, features):
            return PortableReply(
                OutboundMessage.from_text(
                    "该操作当前未对你开放。", request_succeeded=False
                )
            )

        async def query(player_id: int, context: MessageInputContext) -> PortableReply:
            return await query_player_extension(
                action, player_id, context, features, sessions
            )

        async def confirmed_query(
            player_id: int, selected: MessageInputContext
        ) -> PortableReply:
            if player_service is None or not reference or not action.offer_binding:
                return await query(player_id, selected)
            return await confirm_shortcut_binding(
                player_service, sessions, player_id, selected, query
            )

        return await select_player_target(
            reference,
            context,
            resolver,
            sessions,
            confirmed_query,
            title="请选择要查询的玩家：",
        )

    return execute
