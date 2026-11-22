# SPDX-License-Identifier: MIT
"""Public player shortcut replies and their nested Somua navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply
from ironsbot.services.portable_somua_commands import (
    present_somua_overview,
    somua_access_error,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
)
from ironsbot.services.seer.somua_models import SomuaOverviewReply

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import ProgressReporter
    from ironsbot.services.seer.player_id_resolver import (
        PlayerIdResolver,
        PlayerTargetSource,
    )
    from ironsbot.services.seer.player_service import PlayerService


async def player_shortcut_reply(  # noqa: PLR0913 - shared query/navigation ports
    service: PlayerService,
    command: PlayerShortcutCommand,
    context: MessageInputContext,
    *,
    sessions: PortableQuerySessions,
    features: FeatureService,
    resolver: PlayerIdResolver,
    target_source: PlayerTargetSource = "numeric",
) -> PortableReply:
    if command.kind in {"somua", "somua_detail"}:
        error = somua_access_error(
            context,
            command.player_id,
            features=features,
            resolver=resolver,
            source=target_source,
        )
        if error is not None:
            return PortableReply(
                OutboundMessage.from_text(error, request_succeeded=False)
            )

    async def execute(send_status: ProgressReporter) -> OutboundMessage:
        reply = await execute_player_shortcut(
            service,
            command,
            context.message.actor,
            conversation=context.message.conversation,
            send_status=send_status,
        )
        if isinstance(reply, SomuaOverviewReply):

            async def detail(
                sequence: int, selected: MessageInputContext
            ) -> PortableReply:
                return await player_shortcut_reply(
                    service,
                    PlayerShortcutCommand(
                        "somua_detail", command.player_id, somua_sequence=sequence
                    ),
                    selected,
                    sessions=sessions,
                    features=features,
                    resolver=resolver,
                    target_source=target_source
                    if selected.message.actor == context.message.actor
                    else "shared_menu",
                )

            return present_somua_overview(
                reply,
                command.player_id,
                context,
                sessions=sessions,
                features=features,
                resolver=resolver,
                source=target_source,
                query=detail,
            )
        return reply.to_outbound()

    return await progress_operation_reply(execute)
