# SPDX-License-Identifier: MIT
"""Platform-neutral player commands keyed by opaque actor identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.commands import parse_confirmation
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.semantic_requests import ActionDefinition, SemanticTarget
from ironsbot.services.operations.request_feedback import request_feedback_scope
from ironsbot.services.portable_query_sessions import PortableTextInputSpec
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply
from ironsbot.services.portable_seer_commands import query_portable_team_ids
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailActionRequest,
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_query import (
    available_player_detail_requests,
    extract_player_binding_arg,
    extract_player_query_arg,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PLAYER_SHORTCUT_ACTIONS,
    PlayerShortcutCommand,
    PlayerShortcutTargetCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
    player_request_admission_message,
    player_semantic_target,
)
from ironsbot.services.seer.query_result import QueryChoice, QueryResult

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, ProgressReporter
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_service_models import (
        PendingPlayerQuery,
        PlayerQueryResult,
    )
    from ironsbot.services.seer.team import SeerTeamQueryService

_INVALID_BINDING_CONFIRMATION = "binding session accepted an invalid confirmation"


def build_portable_player_operations(  # noqa: PLR0913 - explicit composition dependencies
    service: PlayerService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    features: FeatureService | None = None,
    extensions: PlayerDetailExtensionRegistry | None = None,
    *,
    team_query: SeerTeamQueryService | None = None,
) -> dict[str, PortableOperation]:
    owner = _PortablePlayerOperations(
        service,
        resolver,
        sessions,
        features,
        extensions or PlayerDetailExtensionRegistry(),
        team_query,
    )
    operations: dict[str, PortableOperation] = {
        "seer.player.query": owner.query,
        "seer.player.default": owner.shortcut,
        "seer.player.bind": owner.bind,
        "seer.player.unbind": owner.unbind,
    }
    for action in owner.extensions.actions():
        command_id = action.command_help_id
        if command_id in operations:
            msg = f"player extension command id collides with a built-in: {command_id}"
            raise ValueError(msg)
        operations[command_id] = owner.extension_shortcut
    return operations


@dataclass(frozen=True, slots=True)
class _PortablePlayerOperations:
    service: PlayerService
    resolver: PlayerIdResolver
    sessions: PortableQuerySessions
    features: FeatureService | None
    extensions: PlayerDetailExtensionRegistry
    team_query: SeerTeamQueryService | None

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
        return _prepare_player_query_reply(self, context, result)

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
        return _prepare_player_query_reply(self, context, result)

    async def unbind(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(self.service.unbind(context.message.actor))

    async def shortcut(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply | OutboundMessage:
        resolved = resolve_portable_player_shortcut(
            text,
            context,
            self.resolver,
        )
        if resolved is None:
            msg = f"catalog accepted input that its shortcut parser rejected: {text!r}"
            raise ValueError(msg)
        if resolved.error is not None:
            return OutboundMessage.from_text(resolved.error)
        command = resolved.command
        if command is None:
            return OutboundMessage.from_text(unbound_player_shortcut_message())

        async def execute(report: ProgressReporter):
            reply = await execute_player_shortcut(
                self.service,
                command,
                context.message.actor,
                conversation=context.message.conversation,
                send_status=report,
            )
            return reply.to_outbound()

        return await progress_operation_reply(execute)

    async def extension_shortcut(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply | OutboundMessage:
        resolved = resolve_portable_player_extension(
            text,
            context,
            self.resolver,
            self.extensions,
        )
        if resolved is None:
            msg = f"catalog accepted input that no player extension owns: {text!r}"
            raise ValueError(msg)
        if resolved.error is not None:
            return OutboundMessage.from_text(resolved.error)
        if resolved.player_id is None:
            return OutboundMessage.from_text(unbound_player_shortcut_message())
        return await _execute_player_detail(
            self.service,
            context,
            resolved.action,
            player_id=resolved.player_id,
        )


@dataclass(frozen=True, slots=True)
class PortablePlayerShortcutResolution:
    target: PlayerShortcutTargetCommand
    command: PlayerShortcutCommand | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PortablePlayerExtensionResolution:
    action: PlayerDetailExtensionAction
    player_id: int | None
    error: str | None = None


def resolve_portable_player_shortcut(
    text: str,
    context: MessageInputContext,
    resolver: PlayerIdResolver,
) -> PortablePlayerShortcutResolution | None:
    """Parse and resolve one shortcut identically for every transport."""

    target = parse_player_shortcut_command(text)
    if target is None:
        return None
    resolution = resolver.resolve(context, target.player_reference)
    if resolution.error is not None:
        return PortablePlayerShortcutResolution(target, None, resolution.error)
    if resolution.player_id is None:
        return PortablePlayerShortcutResolution(
            target,
            None,
            unbound_player_shortcut_message(),
        )
    return PortablePlayerShortcutResolution(
        target,
        PlayerShortcutCommand(target.kind, resolution.player_id),
    )


def resolve_portable_player_extension(
    text: str,
    context: MessageInputContext,
    resolver: PlayerIdResolver,
    extensions: PlayerDetailExtensionRegistry,
) -> PortablePlayerExtensionResolution | None:
    """Parse and resolve one registered extension command for every transport."""

    target = extensions.resolve_direct_command(text)
    if target is None:
        return None
    action, player_reference = target
    resolution = resolver.resolve(context, player_reference or None)
    if resolution.error is not None:
        return PortablePlayerExtensionResolution(action, None, resolution.error)
    if resolution.player_id is None:
        return PortablePlayerExtensionResolution(
            action,
            None,
            unbound_player_shortcut_message(),
        )
    return PortablePlayerExtensionResolution(action, resolution.player_id)


def _prepare_player_query_reply(
    owner: _PortablePlayerOperations,
    context: MessageInputContext,
    result: PlayerQueryResult,
) -> PortableReply:
    if result.message:
        return _text_reply(result.message)
    pending = result.pending
    if pending is None:
        msg = "player query returned neither a message nor pending data"
        raise ValueError(msg)

    if result.offer_binding:

        async def submit_binding(text: str) -> PortableReply:
            accepted = parse_confirmation(text)
            if accepted is None:
                raise ValueError(_INVALID_BINDING_CONFIRMATION)
            owner.service.save_binding_choice(
                context.message.actor,
                pending,
                accepted=accepted,
                replacing_existing=result.binding_replacement is not None,
            )
            return _prepare_player_menu(owner, context, pending)

        prompt = owner.sessions.offer_text_input(
            context,
            PortableTextInputSpec(
                submit=submit_binding,
                prompt=OutboundMessage.from_text(
                    owner.service.binding_offer(
                        pending,
                        replacement=result.binding_replacement,
                    )
                ),
                accept=lambda text: parse_confirmation(text) is not None,
            ),
        )
        return PortableReply(prompt)
    return _prepare_player_menu(owner, context, pending)


def _prepare_player_menu(
    owner: _PortablePlayerOperations,
    context: MessageInputContext,
    pending: PendingPlayerQuery,
) -> PortableReply:
    requests = available_player_detail_requests(
        has_collection=pending.section_plan.has_collection,
        has_peak=pending.section_plan.needs_peak_section,
        has_autocard=pending.section_plan.has_autocard_rank,
    )
    builtins = tuple(
        PlayerShortcutCommand(
            request.kind,
            pending.player_id,
            pending.base_snapshot,
        )
        for request in requests
    )
    visible_extensions = tuple(
        action
        for action in owner.extensions.actions()
        if owner.features is None
        or owner.features.is_feature_allowed(
            context.message.actor,
            context.message.conversation,
            action.feature,
        )
    )

    async def select(
        selection: PlayerShortcutCommand
        | PlayerDetailExtensionAction
        | _PlayerTeamSelection,
    ) -> PortableReply:
        if isinstance(selection, _PlayerTeamSelection):
            if owner.team_query is None or owner.features is None:
                return _text_reply("该功能当前未对你开放。")
            return PortableReply(
                await query_portable_team_ids(
                    owner.team_query,
                    owner.features,
                    context,
                    (selection.team_id,),
                )
            )
        return await _execute_player_detail(
            owner.service,
            context,
            selection,
            player_id=pending.player_id,
        )

    choices: list[
        QueryChoice[
            PlayerShortcutCommand | PlayerDetailExtensionAction | _PlayerTeamSelection
        ]
    ] = [
        QueryChoice(
            name=f"【{request.menu_label}】",
            description="",
            value=command,
            semantic_target=player_semantic_target(pending.player_id),
            semantic_action=PLAYER_SHORTCUT_ACTIONS[command.kind],
        )
        for request, command in zip(requests, builtins, strict=True)
    ]
    choices.extend(
        QueryChoice(
            name=f"【{action.label}】",
            description="",
            value=action,
            semantic_target=player_semantic_target(pending.player_id),
            semantic_action=action.action,
        )
        for action in visible_extensions
    )
    snapshot = pending.base_snapshot
    if (
        snapshot is not None
        and snapshot.team_id > 0
        and owner.team_query is not None
        and owner.features is not None
        and owner.features.is_feature_allowed(
            context.message.actor,
            context.message.conversation,
            "seer_team",
        )
    ):
        choices.append(
            QueryChoice(
                name=(
                    f"【战队】{snapshot.team_name.strip() or '未知战队'}"
                    f"（战队ID：{snapshot.team_id}）"
                ),
                description="",
                value=_PlayerTeamSelection(snapshot.team_id),
                semantic_target=SemanticTarget(
                    str(snapshot.team_id), f"战队 {snapshot.team_id}"
                ),
                semantic_action=ActionDefinition(
                    "seer.team.query", "战队查询", cooldown_key="seer_team"
                ),
            )
        )
    menu = owner.sessions.offer(
        context,
        QueryResult(choices=tuple(choices)),
        select=select,
        prompt_title=f"{pending.player_message}\n回复数字查看详情：",
        not_found_message=pending.player_message,
        keep_open=True,
        exit_message="已退出米米号详情查询。",
    )

    def delivered() -> None:
        owner.service.record_returned_query(context.message.actor, pending)
        owner.service.start_background_refresh(
            pending,
            conversation=context.message.conversation,
        )

    return PortableReply(menu, on_delivered=delivered)


@dataclass(frozen=True, slots=True)
class _PlayerTeamSelection:
    team_id: int


async def _execute_player_detail(
    service: PlayerService,
    context: MessageInputContext,
    selection: PlayerShortcutCommand | PlayerDetailExtensionAction,
    *,
    player_id: int,
) -> PortableReply:
    async def execute(report: ProgressReporter) -> OutboundMessage:
        if isinstance(selection, PlayerShortcutCommand):
            reply = await execute_player_shortcut(
                service,
                selection,
                context.message.actor,
                conversation=context.message.conversation,
                send_status=report,
            )
        else:

            async def send_status(label: str, *, queued: bool) -> None:
                await report(player_request_admission_message(label, queued=queued))

            with request_feedback_scope(selection.action.label, send_status):
                reply = await selection.query(
                    PlayerDetailActionRequest(
                        player_id=player_id,
                        actor=context.message.actor,
                        conversation=context.message.conversation,
                    )
                )
        return reply.to_outbound()

    return await progress_operation_reply(execute)


def _text_reply(message: str) -> PortableReply:
    return PortableReply(OutboundMessage.from_text(message))
