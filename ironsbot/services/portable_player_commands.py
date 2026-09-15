# SPDX-License-Identifier: MIT
"""Platform-neutral player commands keyed by opaque actor identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.authorization import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailActionRequest,
    PlayerDetailExtensionAction,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_query import (
    available_player_detail_requests,
    extract_player_binding_arg,
    extract_player_query_arg,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
)
from ironsbot.services.seer.query_result import QueryChoice, QueryResult

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_service_models import PlayerQueryResult


def build_portable_player_operations(
    service: PlayerService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    features: FeatureService | None = None,
    extensions: PlayerDetailExtensionRegistry | None = None,
) -> dict[str, PortableOperation]:
    owner = _PortablePlayerOperations(service, resolver, sessions, features, extensions)
    return {
        "seer.player.query": owner.query,
        "seer.player.default": owner.shortcut,
        "seer.player.bind": owner.bind,
        "seer.player.unbind": owner.unbind,
    }


@dataclass(frozen=True, slots=True)
class _PortablePlayerOperations:
    service: PlayerService
    resolver: PlayerIdResolver
    sessions: PortableQuerySessions
    features: FeatureService | None
    extensions: PlayerDetailExtensionRegistry | None

    async def query(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        reference = extract_player_query_arg(text)
        if reference is None:
            msg = f"catalog accepted input that its player parser rejected: {text!r}"
            raise ValueError(msg)
        resolution = self.resolver.resolve(context, reference or None)
        if resolution.error is not None:
            return _text_reply(resolution.error)
        if resolution.player_id is None:
            return _text_reply(unbound_player_shortcut_message())
        result = await self.service.query(
            resolution.player_id,
            actor=context.message.actor,
            explicit=resolution.offer_binding,
            conversation=context.message.conversation,
        )
        return _prepare_player_query_reply(
            self.service,
            self.sessions,
            context,
            result,
            self.features,
            self.extensions,
        )

    async def bind(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        reference = extract_player_binding_arg(text)
        if reference is None:
            msg = f"catalog accepted input that its binding parser rejected: {text!r}"
            raise ValueError(msg)
        resolution = self.resolver.resolve(
            context,
            reference or None,
            allow_default_binding=False,
        )
        if resolution.error is not None:
            return _text_reply(resolution.error)
        if resolution.player_id is None:
            return _text_reply(unbound_player_shortcut_message())
        result = await self.service.bind_player(
            resolution.player_id,
            actor=context.message.actor,
            conversation=context.message.conversation,
        )
        if result.pending is not None and result.binding_replacement is not None:
            self.service.save_binding_choice(
                context.message.actor,
                result.pending,
                accepted=True,
                replacing_existing=True,
            )
        return _prepare_player_query_reply(
            self.service,
            self.sessions,
            context,
            result,
            self.features,
            self.extensions,
        )

    async def unbind(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(
            self.service.unbind(context.message.actor)
        )

    async def shortcut(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        parsed = parse_player_shortcut_command(text)
        if parsed is None:
            msg = f"catalog accepted input that its shortcut parser rejected: {text!r}"
            raise ValueError(msg)
        resolution = self.resolver.resolve(context, parsed.player_reference)
        if resolution.error is not None:
            return OutboundMessage.from_text(resolution.error)
        if resolution.player_id is None:
            return OutboundMessage.from_text(unbound_player_shortcut_message())
        reply = await execute_player_shortcut(
            self.service,
            PlayerShortcutCommand(parsed.kind, resolution.player_id),
            context.message.actor,
            conversation=context.message.conversation,
        )
        return reply.to_outbound()


def _prepare_player_query_reply(  # noqa: PLR0913 - explicit menu dependencies
    service: PlayerService,
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    result: PlayerQueryResult,
    features: FeatureService | None,
    extensions: PlayerDetailExtensionRegistry | None,
) -> PortableReply:
    if result.message:
        return _text_reply(result.message)
    pending = result.pending
    if pending is None:
        msg = "player query returned neither a message nor pending data"
        raise ValueError(msg)

    player_message = pending.player_message
    if result.offer_binding:
        player_message += (
            f"\n\n发送“绑定米米号{pending.player_id}”可设为默认米米号。"
        )
    requests = available_player_detail_requests(
        has_collection=pending.section_plan.has_collection,
        has_peak=pending.section_plan.needs_peak_section,
        has_autocard=pending.section_plan.has_autocard_rank,
    )
    extension_actions = (
        ()
        if features is None or extensions is None
        else tuple(
            action
            for action in extensions.actions()
            if features.is_feature_allowed(
                context.message.actor,
                context.message.conversation,
                action.feature,
            )
        )
    )

    async def select(
        command: PlayerShortcutCommand | PlayerDetailExtensionAction,
    ) -> QueryResult[object]:
        if isinstance(command, PlayerDetailExtensionAction):
            reply = await command.query(
                PlayerDetailActionRequest(
                    player_id=pending.player_id,
                    actor=context.message.actor,
                    conversation=context.message.conversation,
                    can_manage=(
                        context.message.group_role in GROUP_MANAGER_ROLES
                        or (
                            features is not None
                            and features.is_actor_superuser(context.message.actor)
                        )
                    ),
                )
            )
        else:
            reply = await execute_player_shortcut(
                service,
                command,
                context.message.actor,
                conversation=context.message.conversation,
            )
        return QueryResult(reply=reply)

    menu = sessions.offer(
        context,
        QueryResult(
            choices=(
                *(
                QueryChoice[PlayerShortcutCommand | PlayerDetailExtensionAction](
                    name=f"【{request.menu_label}】",
                    description="",
                    value=PlayerShortcutCommand(
                        request.kind,
                        pending.player_id,
                        pending.base_snapshot,
                    ),
                )
                for request in requests
                ),
                *(
                    QueryChoice[PlayerShortcutCommand | PlayerDetailExtensionAction](
                        name=f"【{action.label}】",
                        description="",
                        value=action,
                    )
                    for action in extension_actions
                ),
            )
        ),
        select=select,
        prompt_title=f"{player_message}\n回复数字查看详情：",
        not_found_message=player_message,
    )

    def delivered() -> None:
        service.record_returned_query(context.message.actor, pending)
        service.start_background_refresh(
            pending,
            conversation=context.message.conversation,
        )

    return PortableReply(menu, on_delivered=delivered)


def _text_reply(message: str) -> PortableReply:
    return PortableReply(OutboundMessage.from_text(message))
