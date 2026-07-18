# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.player_binding import get_player_binding
from ironsbot.services.seer.player_query import (
    player_query_failure_message,
    player_query_timeout_message,
)
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    fetch_player_shortcut_message,
    parse_player_shortcut_command,
)
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.services.seer.resources import SeerQueryResources

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"


async def _is_player_shortcut(event: Event, state: T_State) -> bool:
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    state[_SHORTCUT_COMMAND_KEY] = command
    return True


async def handle_player_shortcut(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    config = resources.config
    headless = resources.headless
    command: PlayerShortcutCommand = state[_SHORTCUT_COMMAND_KEY]
    player_id = command.player_id
    if player_id is None:
        binding = get_player_binding(
            config.player.binding.path,
            event.user_id,
        )
        player_id = binding.player_id
    if player_id is None:
        await finish_event_reply(
            matcher,
            event,
            "尚未设置默认米米号，请发送“米米号+数字”查询，"
            "或直接在本指令后填写米米号。",
            mention_sender=True,
        )
        return

    try:
        game = headless.get_game()
        with headless_operation(
            "米米号快捷详情查询",
            f"米米号 {player_id}",
            source="米米号快捷详情查询",
        ):
            message = await asyncio.wait_for(
                fetch_player_shortcut_message(
                    resources.local_rank,
                    game,
                    command=command,
                    player_id=player_id,
                ),
                timeout=config.player.detail_timeout_seconds,
            )
        await headless.mark_available(
            source="米米号快捷详情查询",
            user_id=int(game.user_id),
        )
    except TimeoutError:
        message = player_query_timeout_message(player_id)
    except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
        message = format_player_query_error(player_id, error)
    except Exception as error:  # noqa: BLE001
        message = player_query_failure_message(player_id, error)

    await finish_event_reply(matcher, event, message, mention_sender=True)


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
        rule=seer_feature_rule(group.resources.features, "seer_player")
        & Rule(_is_player_shortcut)
        & no_reply(),
        priority=group.matcher_priority("seer_player", 1),
        block=True,
    )
    matcher.append_handler(partial(handle_player_shortcut, group.resources))
