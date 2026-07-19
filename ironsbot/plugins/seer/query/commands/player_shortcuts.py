# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import no_reply
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    parse_player_shortcut_command,
)

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.services.seer.player_service import PlayerService

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"


async def _is_player_shortcut(event: Event, state: T_State) -> bool:
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    state[_SHORTCUT_COMMAND_KEY] = command
    return True


async def handle_player_shortcut(
    service: PlayerService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command: PlayerShortcutCommand = state[_SHORTCUT_COMMAND_KEY]
    message = await service.shortcut(command, event.user_id)
    await finish_event_reply(matcher, event, message)


def _shortcut_command_id(
    _event: Event,
    state: T_State,
) -> str:
    command = state.get(_SHORTCUT_COMMAND_KEY)
    kind = str(getattr(command, "kind", "")).strip()
    return f"seer_player_{kind}" if kind else "seer_player"


def install(group: SeerMatcherGroup) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command(_shortcut_command_id),
        rule=seer_feature_rule(group.features, "seer_player")
        & Rule(_is_player_shortcut)
        & no_reply(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    matcher.append_handler(
        bind_async(handle_player_shortcut, group.resources.player)
    )
