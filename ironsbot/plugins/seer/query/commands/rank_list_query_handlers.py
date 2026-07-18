# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.rank_display import rank_display_limit_for_group
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
    RankListCommand,
    RankPlayerCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_usage import build_rank_help_message
from ironsbot.shared.messaging import finish_event_reply

from ..config import get_player_query_config
from .rank_list_actions import (
    build_global_rank_message,
    build_global_rank_player_message,
    build_global_rank_score_message,
    build_local_rank_message,
)
from .rank_list_context import (
    RANK_LIST_COMMAND_KEY,
    RANK_PLAYER_COMMAND_KEY,
    RANK_SCORE_COMMAND_KEY,
    event_group_id,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.integrations.headless_seer.game import SeerGame


async def handle_help(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(matcher, event, build_rank_help_message())


async def handle_list(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    game: SeerGame,
) -> None:
    command: RankListCommand = state[RANK_LIST_COMMAND_KEY]

    if command.kind == "global":
        await finish_event_reply(
            matcher,
            event,
            await build_global_rank_message(
                game,
                GLOBAL_RANKS[command.rank_key],
                command,
            ),
        )

    await finish_event_reply(
        matcher,
        event,
        build_local_rank_message(LOCAL_RANKS[command.rank_key], command),
    )


async def handle_score(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    game: SeerGame,
) -> None:
    command: RankScoreCommand = state[RANK_SCORE_COMMAND_KEY]
    await finish_event_reply(
        matcher,
        event,
        await build_global_rank_score_message(
            game,
            GLOBAL_RANKS[command.rank_key],
            command,
            display_limit=rank_display_limit_for_group(event_group_id(event)),
        ),
    )


async def handle_player(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    game: SeerGame,
) -> None:
    command: RankPlayerCommand = state[RANK_PLAYER_COMMAND_KEY]
    spec = GLOBAL_RANKS[command.rank_key]
    try:
        message = await asyncio.wait_for(
            build_global_rank_player_message(game, command),
            timeout=get_player_query_config().detail_timeout_seconds,
        )
    except TimeoutError:
        message = f"❌ {spec.title}玩家查询超时，请稍后再试。"
    except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
        message = format_player_query_error(command.player_id, error)
    except Exception as error:  # noqa: BLE001
        message = f"❌ {spec.title}玩家查询失败：{error}"
    await finish_event_reply(matcher, event, message)
