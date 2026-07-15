# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.integrations.headless_seer.client import get_game_client
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.packets import ensure_extended_packets
from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_query import (
    PlayerDetailMessages,
    extract_player_query_arg,
    optional_player_extra,
    plan_player_query_sections,
    player_query_failure_message,
    player_query_in_progress_message,
    player_query_timeout_message,
    player_query_wait_message,
)
from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
from ironsbot.services.seer.sequ_extra import (
    UnityPeakInfo,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
)
from ironsbot.shared.messaging.query_guard import QueryGuard
from ironsbot.utils.rule import BOT_COMMAND_ARG_KEY, no_reply

from ..config import (
    get_local_rank_config,
    get_player_query_config,
    get_team_query_config,
)
from ..group import matcher_group, seer_feature_rule
from ._args import parse_numeric_id
from .player_context import PLAYER_ID_KEY
from .player_detail_conversation import (
    send_player_info_with_detail_prompt,
)
from .player_detail_fetch import create_player_detail_task

PLAYER_QUERY_GUARD = QueryGuard(
    success_namespace="seer.player_query.success",
    failure_namespace="seer.player_query.failure",
    success_cooldown=lambda: get_player_query_config().rate_limit_seconds,
    failure_cooldown=lambda: get_player_query_config().failure_rate_limit_seconds,
)


async def _is_player_id_query(event: Event, state: T_State) -> bool:
    arg = extract_player_query_arg(event.get_plaintext())
    if arg is None or not arg.isdigit():
        return False

    state[BOT_COMMAND_ARG_KEY] = arg
    return True


async def _is_invalid_player_text_query(event: Event) -> bool:
    arg = extract_player_query_arg(event.get_plaintext())
    return arg is not None and not arg.isdigit()


player_invalid_text_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_player")
    & Rule(_is_invalid_player_text_query)
    & no_reply(),
    priority=get_matcher_priority("seer_player", 1),
    block=True,
)

player_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_player") & Rule(_is_player_id_query) & no_reply(),
    priority=get_matcher_priority("seer_player", 1),
    block=True,
)


@player_invalid_text_matcher.handle()
async def block_invalid_player_text_query() -> None:
    return


def _log_player_extra_error(label: str, _error: Exception) -> None:
    logger.opt(exception=True).warning(f"米米号扩展字段获取失败：{label}")


@player_matcher.handle()
async def validate_player_id(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    player_id = await parse_numeric_id(
        matcher,
        state,
        min_value=1,
        max_value=2_000_000_000,
        error_message="❌ 米米号无效，请输入纯数字米米号。",
    )
    state[PLAYER_ID_KEY] = player_id
    in_progress_player_id = PLAYER_QUERY_GUARD.in_progress_subject(event.user_id)
    if in_progress_player_id is not None:
        await finish_event_reply(
            matcher,
            event,
            player_query_in_progress_message(in_progress_player_id),
            mention_sender=True,
        )
    remaining = PLAYER_QUERY_GUARD.remaining_seconds(event.user_id)
    if remaining > 0:
        await finish_event_reply(
            matcher,
            event,
            player_query_wait_message(remaining),
            mention_sender=True,
        )
    PLAYER_QUERY_GUARD.set_in_progress(event.user_id, player_id)


@player_matcher.handle()
async def handle_player(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    ensure_extended_packets()
    player_id: int = state[PLAYER_ID_KEY]
    extra_errors: list[str] = []
    player_config = get_player_query_config()
    local_rank_config = get_local_rank_config()
    section_plan = plan_player_query_sections(
        player_config.sections,
        local_rank_enabled=local_rank_config.enabled,
    )
    detail_task: asyncio.Task[PlayerDetailMessages] | None = None

    try:
        game = get_game_client()
        with headless_operation(
            "米米号查询",
            f"米米号 {player_id}",
            source="米米号查询",
        ):
            user_info, more_info, online_info = await asyncio.wait_for(
                asyncio.gather(
                    game.get_user_info(player_id),
                    game.get_more_user_info(player_id),
                    optional_player_extra(
                        "在线状态",
                        section_plan.needs_online_info,
                        lambda: game.get_user_online_info(player_id),
                        None,
                        extra_errors,
                        on_error=_log_player_extra_error,
                    ),
                ),
                timeout=player_config.timeout_seconds,
            )
        await mark_headless_available(
            source="米米号查询",
            user_id=int(game.user_id),
        )

        team_name = "无"
        if getattr(user_info, "team_id", 0) > 0:
            try:
                team_info = await asyncio.wait_for(
                    game.get_team_info(user_info.team_id),
                    timeout=min(
                        5.0,
                        get_team_query_config().timeout_seconds,
                    ),
                )
                team_name = team_info.name
            except Exception:  # noqa: BLE001
                team_name = str(user_info.team_id)

        if section_plan.needs_detail_task:
            detail_task = create_player_detail_task(
                player_id=player_id,
                user_info=user_info,
                more_info=more_info,
                has_collection=section_plan.has_collection,
                needs_peak_section=section_plan.needs_peak_section,
                has_autocard_rank=section_plan.has_autocard_rank,
                show_local_rank=section_plan.show_local_rank,
            )

        player_message = format_compact_player_info(
            user_info,
            more_info,
            team_name=team_name,
            online_info=online_info,
            unity_peak=UnityPeakInfo(),
            peak_rank_summary=PeakSeasonRankSummary.empty(),
            local_summary=LocalRankSummary(),
            has_collection=section_plan.has_collection,
            has_peak=section_plan.needs_peak_section,
            has_autocard=section_plan.has_autocard_rank,
            show_peak=False,
            extra_errors=extra_errors,
        )

    except FinishedException:
        raise
    except (SocketRecvError, NotLoggedInError, DisconnectedError) as e:
        if isinstance(e, (NotLoggedInError, DisconnectedError)):
            await mark_headless_unavailable(str(e), source="米米号查询")
        PLAYER_QUERY_GUARD.clear_in_progress(event.user_id)
        PLAYER_QUERY_GUARD.penalize_failure(event.user_id)
        await finish_event_reply(
            matcher,
            event,
            format_player_query_error(player_id, e),
            mention_sender=True,
        )
        return
    except TimeoutError:
        PLAYER_QUERY_GUARD.clear_in_progress(event.user_id)
        PLAYER_QUERY_GUARD.penalize_failure(event.user_id)
        await finish_event_reply(
            matcher,
            event,
            player_query_timeout_message(player_id),
            mention_sender=True,
        )
        return
    except Exception as e:  # noqa: BLE001
        PLAYER_QUERY_GUARD.clear_in_progress(event.user_id)
        PLAYER_QUERY_GUARD.penalize_failure(event.user_id)
        await finish_event_reply(
            matcher,
            event,
            player_query_failure_message(player_id, e),
            mention_sender=True,
        )
        return

    PLAYER_QUERY_GUARD.clear_in_progress(event.user_id)
    PLAYER_QUERY_GUARD.penalize_success(event.user_id)
    await send_player_info_with_detail_prompt(
        matcher,
        event,
        state,
        player_message=player_message,
        detail_task=detail_task,
        has_collection=section_plan.has_collection,
        has_peak=section_plan.needs_peak_section,
        has_autocard=section_plan.has_autocard_rank,
    )
