# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import member_target_command
from ironsbot.runtime.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
)
from ironsbot.services.operations.request_feedback import request_feedback_scope
from ironsbot.services.seer.ids import is_valid_player_id
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
    player_request_admission_message,
    player_shortcut_semantic_request,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player import PlayerCommandDependencies
from .player_target import resolve_player_target

if TYPE_CHECKING:
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.query_result import QueryReply

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"
_EXTENSION_SHORTCUT_COMMAND_KEY = "_player_extension_shortcut_command"


@dataclass(frozen=True, slots=True)
class PlayerExtensionShortcutCommand:
    """A public-resolved extension action plus an optional numeric target."""

    action: PlayerDetailExtensionAction
    player_id: int | None


def _build_shortcut_reply_message(reply: QueryReply) -> str | Message:
    if reply.image is None:
        return f"{reply.leading_text}{reply.text}"

    message = Message()
    if reply.leading_text:
        message += MessageSegment.text(reply.leading_text)
    message += MessageSegment.image(reply.image)
    if reply.text:
        message += MessageSegment.text(reply.text)
    return message


async def _is_player_shortcut(
    event: Event,
    state: T_State,
    *,
    dependencies: PlayerCommandDependencies,
) -> bool:
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    if command.player_reference is not None:
        player_reference = command.player_reference
        group_id = getattr(event, "group_id", None)
        player_id = dependencies.player_accounts.resolve_player_id(
            player_reference,
            group_id=group_id if isinstance(group_id, int) else None,
        )
        if player_id is None:
            return False
        command = PlayerShortcutCommand(
            kind=command.kind,
            player_id=player_id,
        )
    state[_SHORTCUT_COMMAND_KEY] = command
    return True


async def _is_player_extension_shortcut(
    event: Event,
    state: T_State,
    *,
    dependencies: PlayerCommandDependencies,
) -> bool:
    resolved = dependencies.detail_extensions.resolve_direct_command(
        event.get_plaintext()
    )
    if resolved is None:
        return False
    action, player_reference = resolved
    if not event_is_feature_allowed(dependencies.features, event, action.feature):
        return False
    player_id = None
    if player_reference:
        group_id = getattr(event, "group_id", None)
        player_id = dependencies.player_accounts.resolve_player_id(
            player_reference,
            group_id=group_id if isinstance(group_id, int) else None,
        )
        if player_id is None:
            return False
    state[_EXTENSION_SHORTCUT_COMMAND_KEY] = PlayerExtensionShortcutCommand(
        action,
        player_id,
    )
    return True


async def handle_player_shortcut(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    service = dependencies.player
    command: PlayerShortcutCommand = state[_SHORTCUT_COMMAND_KEY]
    target = resolve_player_target(
        event,
        numeric_player_id=command.player_id,
        binding_for_user=service.default_player_id,
    )
    if target.error is not None:
        await finish_event_reply(matcher, event, target.error)
        return
    command = PlayerShortcutCommand(kind=command.kind, player_id=target.player_id)

    async def send_status(message: str) -> None:
        await send_event_reply(matcher, event, message)

    reply = await execute_player_shortcut(
        service,
        command,
        event.user_id,
        group_id=event_group_id(event),
        send_status=send_status,
    )
    await finish_event_reply(
        matcher,
        event,
        _build_shortcut_reply_message(reply),
    )


async def handle_player_extension_shortcut(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutCommand):
        return
    target = resolve_player_target(
        event,
        numeric_player_id=command.player_id,
        binding_for_user=dependencies.player.default_player_id,
    )
    if target.error is not None:
        await finish_event_reply(matcher, event, target.error)
        return
    if target.player_id is None:
        await finish_event_reply(matcher, event, unbound_player_shortcut_message())
        return
    async def send_status(label: str, *, queued: bool) -> None:
        await send_event_reply(
            matcher,
            event,
            player_request_admission_message(label, queued=queued),
        )

    with request_feedback_scope(command.action.action.label, send_status):
        reply = await command.action.query(
            target.player_id,
            event.user_id,
            event_group_id(event),
        )
    await finish_event_reply(matcher, event, _build_shortcut_reply_message(reply))


def _shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    kind = str(getattr(command, "kind", "")).strip()
    return f"seer_player_{kind}" if kind else "seer_player"


def _shortcut_semantic_request(
    service: PlayerService,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    target = resolve_player_target(
        event,
        numeric_player_id=getattr(command, "player_id", None),
        binding_for_user=service.default_player_id,
    )
    player_id = target.player_id
    kind = getattr(command, "kind", None)
    if not isinstance(player_id, int) or not is_valid_player_id(player_id):
        return None
    if kind not in {"collection", "peak", "autocard"}:
        return None
    return player_shortcut_semantic_request(
        kind=kind,
        player_id=player_id,
        source=SemanticRequestSource.DIRECT,
    )


def _extension_shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutCommand):
        return "seer_player_extension"
    return command.action.action.cooldown_key or command.action.id


def _extension_shortcut_semantic_request(
    service: PlayerService,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    command = state.get(_EXTENSION_SHORTCUT_COMMAND_KEY)
    if not isinstance(command, PlayerExtensionShortcutCommand):
        return None
    target = resolve_player_target(
        event,
        numeric_player_id=command.player_id,
        binding_for_user=service.default_player_id,
    )
    if not (
        isinstance(target.player_id, int)
        and is_valid_player_id(target.player_id)
    ):
        return None
    return SemanticRequest(
        action=command.action.action,
        target=player_shortcut_semantic_request(
            kind="collection",
            player_id=target.player_id,
            source=SemanticRequestSource.DIRECT,
        ).target,
        source=SemanticRequestSource.EXTENSION,
    )


def install(group: SeerMatcherGroup) -> None:
    dependencies = PlayerCommandDependencies(
        group.resources.player,
        group.features,
        group.resources.player_detail_extensions,
        group.player_accounts,
    )
    matcher = group.on_message(
        policy=CommandPolicy.command(
            _shortcut_command_id,
            help_ids=("seer.player.default",),
            semantic_request=lambda event, state: _shortcut_semantic_request(
                group.resources.player,
                event,
                state,
            ),
        ),
        rule=seer_feature_rule(group.features, "seer_player")
        & Rule(bind_async(_is_player_shortcut, dependencies=dependencies))
        & member_target_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    matcher.append_handler(
        bind_async(
            handle_player_shortcut,
            dependencies,
        )
    )

    extension_actions = dependencies.detail_extensions.actions()
    if not extension_actions:
        return

    extension_matcher = group.on_message(
        policy=CommandPolicy.command(
            _extension_shortcut_command_id,
            help_ids=tuple(
                action.command_help_id
                for action in extension_actions
            ),
            semantic_request=lambda event, state: _extension_shortcut_semantic_request(
                group.resources.player,
                event,
                state,
            ),
        ),
        rule=Rule(
            bind_async(
                _is_player_extension_shortcut,
                dependencies=dependencies,
            )
        )
        & member_target_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    extension_matcher.append_handler(
        bind_async(handle_player_extension_shortcut, dependencies)
    )
