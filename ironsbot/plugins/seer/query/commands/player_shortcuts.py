# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

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

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import no_reply
from ironsbot.runtime.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
)
from ironsbot.services.seer.ids import is_valid_player_id
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
    player_shortcut_semantic_request,
)

from ..group import SeerMatcherGroup, seer_feature_rule
from .player import PlayerCommandDependencies

if TYPE_CHECKING:
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.query_result import QueryReply

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"


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


async def _is_player_shortcut(event: Event, state: T_State) -> bool:
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    state[_SHORTCUT_COMMAND_KEY] = command
    return True


async def handle_player_shortcut(
    dependencies: PlayerCommandDependencies,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    service = dependencies.player
    command: PlayerShortcutCommand = state[_SHORTCUT_COMMAND_KEY]

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
    player_id = getattr(command, "player_id", None)
    if not isinstance(player_id, int):
        player_id = service.default_player_id(event.user_id)
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


def install(group: SeerMatcherGroup) -> None:
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
        & Rule(_is_player_shortcut)
        & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    matcher.append_handler(
        bind_async(
            handle_player_shortcut,
            PlayerCommandDependencies(
                group.resources.player,
                group.features,
                group.resources.player_detail_extensions,
            ),
        )
    )
