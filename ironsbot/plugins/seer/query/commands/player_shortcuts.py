# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.integrations.headless_seer.client import get_game_client
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.headless_seer_notice.state import mark_headless_available
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
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

from ..config import get_local_rank_config, get_player_query_config
from ..group import matcher_group, seer_feature_rule

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

_SHORTCUT_COMMAND_KEY = "_player_shortcut_command"


async def _is_player_shortcut(event: Event, state: T_State) -> bool:
    command = parse_player_shortcut_command(event.get_plaintext())
    if command is None:
        return False
    state[_SHORTCUT_COMMAND_KEY] = command
    return True


player_shortcut_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_player") & Rule(_is_player_shortcut) & no_reply(),
    priority=get_matcher_priority("seer_player", 1),
    block=True,
)


@player_shortcut_matcher.handle()
async def handle_player_shortcut(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command: PlayerShortcutCommand = state[_SHORTCUT_COMMAND_KEY]
    player_id = command.player_id
    if player_id is None:
        binding = get_player_binding(
            get_player_query_config().binding.path,
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
        game = get_game_client()
        with headless_operation(
            "米米号快捷详情查询",
            f"米米号 {player_id}",
            source="米米号快捷详情查询",
        ):
            message = await asyncio.wait_for(
                fetch_player_shortcut_message(
                    game,
                    command=command,
                    player_id=player_id,
                    local_rank_enabled=get_local_rank_config().enabled,
                ),
                timeout=get_player_query_config().detail_timeout_seconds,
            )
        await mark_headless_available(
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
