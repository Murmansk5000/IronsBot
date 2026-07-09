# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from contextlib import suppress
from typing import Any

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.local_rank import LocalRankSummary, update_local_rank_cache
from ironsbot.services.seer.player_formatting import format_player_detail_messages
from ironsbot.services.seer.player_query import (
    PLAYER_DETAIL_COMMANDS_KEY,
    PLAYER_DETAIL_TASK_KEY,
    PlayerDetailMessages,
    cached_player_detail_message,
    calculate_player_peak_scores,
    optional_player_extra,
    plan_player_detail_fetches,
    plan_player_detail_prompt,
    player_detail_auto_reply_keys,
    player_detail_auto_reply_tasks,
    player_detail_empty_message,
    player_detail_failure_message,
    player_detail_pending_message,
    player_detail_timeout_message,
    resolve_player_detail_reply,
    store_player_detail_messages,
)
from ironsbot.services.seer.rank import (
    fetch_autocard_rank_summary,
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
    get_current_peak_sub_key,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)
from ironsbot.shared.messaging import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.messaging.conversations import command_reply_check

from ..config import get_local_rank_config, get_player_query_config
from .player_context import PLAYER_DETAIL_NAMESPACE, PLAYER_ID_KEY


def _log_player_extra_error(label: str, _error: Exception) -> None:
    logger.opt(exception=True).warning(f"米米号扩展字段获取失败：{label}")


async def handle_player_detail_reply(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    detail_request = resolve_player_detail_reply(event.get_plaintext())
    detail_is_pending = _is_player_detail_task_pending(state)
    message = (
        await _get_player_detail_message(
            state,
            detail_request.key,
            detail_request.label,
            matcher=matcher,
            event=event,
        )
        if detail_request is not None
        else None
    )

    if not message:
        raise FinishedException

    if detail_is_pending:
        await send_event_reply(
            matcher,
            event,
            message,
            mention_sender=True,
        )
        await _continue_player_detail_conversation(
            matcher,
            event,
            state,
            prompt=None,
        )

    await _continue_player_detail_conversation(
        matcher,
        event,
        state,
        prompt=message,
    )


async def _get_player_detail_message(
    state: T_State,
    key: str,
    label: str,
    *,
    matcher: Matcher | None = None,
    event: MessageEvent | None = None,
) -> str:
    task = state.get(PLAYER_DETAIL_TASK_KEY)
    if isinstance(task, asyncio.Task):
        if not task.done():
            if matcher is not None and event is not None:
                _schedule_player_detail_auto_reply(
                    matcher,
                    event,
                    state,
                    key=key,
                    label=label,
                    task=task,
                )
            return player_detail_pending_message(label)

        try:
            detail_messages = task.result()
        except TimeoutError:
            state[PLAYER_DETAIL_TASK_KEY] = None
            return player_detail_timeout_message(label)
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as e:
            state[PLAYER_DETAIL_TASK_KEY] = None
            return format_player_query_error(int(state.get(PLAYER_ID_KEY, 0)), e)
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).warning("米米号后台详情任务失败")
            state[PLAYER_DETAIL_TASK_KEY] = None
            return player_detail_failure_message(label, e)

        store_player_detail_messages(state, detail_messages)
        state[PLAYER_DETAIL_TASK_KEY] = None

    return cached_player_detail_message(state, key)


def _is_player_detail_task_pending(state: T_State) -> bool:
    task = state.get(PLAYER_DETAIL_TASK_KEY)
    return isinstance(task, asyncio.Task) and not task.done()


def _schedule_player_detail_auto_reply(  # noqa: PLR0913
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    key: str,
    label: str,
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    auto_reply_keys = player_detail_auto_reply_keys(state)
    if key in auto_reply_keys:
        return

    auto_reply_keys.add(key)
    auto_reply_task = asyncio.create_task(
        _send_player_detail_auto_reply(
            matcher,
            event,
            state,
            key=key,
            label=label,
            task=task,
        )
    )
    auto_reply_tasks = player_detail_auto_reply_tasks(state)
    auto_reply_tasks.add(auto_reply_task)
    auto_reply_task.add_done_callback(auto_reply_tasks.discard)


async def _send_player_detail_auto_reply(  # noqa: PLR0913
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    key: str,
    label: str,
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    try:
        with suppress(Exception):
            await asyncio.shield(task)

        message = await _get_player_detail_message(state, key, label)
        if not message:
            message = player_detail_empty_message(label)

        await send_event_reply(
            matcher,
            event,
            message,
            mention_sender=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"米米号后台详情自动回复失败：{e}")
    finally:
        player_detail_auto_reply_keys(state).discard(key)


async def _continue_player_detail_conversation(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    prompt: str | None,
) -> None:
    commands = tuple(state.get(PLAYER_DETAIL_COMMANDS_KEY) or ())
    if not commands:
        if prompt is None:
            raise FinishedException
        await finish_event_reply(
            matcher,
            event,
            prompt,
            mention_sender=True,
        )

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_DETAIL_NAMESPACE,
        handlers=[handle_player_detail_reply],
        reply_check=command_reply_check(commands),
        prompt=prompt,
        mention_sender=True,
    )


async def send_player_info_with_detail_prompt(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    player_message: str,
    detail_task: asyncio.Task[PlayerDetailMessages] | None = None,
    has_collection: bool = False,
    has_peak: bool = False,
    has_autocard: bool = False,
) -> None:
    prompt_plan = plan_player_detail_prompt(
        has_collection=has_collection,
        has_peak=has_peak,
        has_autocard=has_autocard,
        supports_conversation=isinstance(event, MessageEvent),
    )

    if detail_task is not None:
        state[PLAYER_DETAIL_TASK_KEY] = detail_task

    state[PLAYER_DETAIL_COMMANDS_KEY] = prompt_plan.commands

    if not prompt_plan.should_enter_conversation:
        if isinstance(event, MessageEvent):
            await finish_event_reply(
                matcher,
                event,
                player_message,
                mention_sender=True,
            )
        else:
            await matcher.finish(player_message)

    if not isinstance(event, MessageEvent):
        await matcher.finish(player_message)

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_DETAIL_NAMESPACE,
        handlers=[handle_player_detail_reply],
        reply_check=command_reply_check(prompt_plan.commands),
        prompt=player_message,
        mention_sender=True,
    )


def _log_unrequested_player_detail_task_error(
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return

    if exception is not None:
        logger.opt(exception=exception).warning("米米号后台详情任务失败")


def create_player_detail_task(  # noqa: PLR0913
    *,
    player_id: int,
    user_info: Any,
    more_info: Any,
    has_collection: bool,
    needs_peak_section: bool,
    has_autocard_rank: bool,
    show_local_rank: bool,
) -> asyncio.Task[PlayerDetailMessages]:
    task = asyncio.create_task(
        asyncio.wait_for(
            _build_player_detail_messages(
                player_id=player_id,
                user_info=user_info,
                more_info=more_info,
                has_collection=has_collection,
                needs_peak_section=needs_peak_section,
                has_autocard_rank=has_autocard_rank,
                show_local_rank=show_local_rank,
            ),
            timeout=get_player_query_config().detail_timeout_seconds,
        )
    )
    task.add_done_callback(_log_unrequested_player_detail_task_error)
    return task


async def _build_player_detail_messages(  # noqa: PLR0913
    *,
    player_id: int,
    user_info: Any,
    more_info: Any,
    has_collection: bool,
    needs_peak_section: bool,
    has_autocard_rank: bool,
    show_local_rank: bool,
) -> PlayerDetailMessages:
    game = get_game_client()
    extra_errors: list[str] = []
    fetch_plan = plan_player_detail_fetches(
        has_collection=has_collection,
        needs_peak_section=needs_peak_section,
        has_autocard_rank=has_autocard_rank,
        local_rank_enabled=get_local_rank_config().enabled,
    )

    unity_part_one, unity_peak = await asyncio.gather(
        optional_player_extra(
            "展示/收集数据",
            fetch_plan.needs_unity_part_one,
            lambda: fetch_unity_part_one(game, player_id),
            UnityPartOneInfo(),
            extra_errors,
            on_error=_log_player_extra_error,
        ),
        optional_player_extra(
            "巅峰数据",
            fetch_plan.needs_unity_peak,
            lambda: fetch_unity_peak(game, player_id),
            UnityPeakInfo(),
            extra_errors,
            on_error=_log_player_extra_error,
        ),
    )
    rank_summary = await optional_player_extra(
        "全服排行",
        fetch_plan.needs_rank_summary,
        lambda: fetch_player_rank_summary(
            game,
            player_id,
            achieve_score=getattr(more_info, "total_achieve", None),
            pet_kind_count=unity_part_one.pet_kind_num,
            skin_score=unity_part_one.skin_num,
        ),
        PlayerRankSummary.empty(),
        extra_errors,
        on_error=_log_player_extra_error,
    )
    peak_sub_key = get_current_peak_sub_key()
    peak_scores = calculate_player_peak_scores(unity_peak)
    peak_rank_summary = await optional_player_extra(
        "巅峰赛季榜",
        needs_peak_section,
        lambda: fetch_peak_season_rank_summary(
            game,
            player_id,
            standard_score=peak_scores.standard,
            wild_score=peak_scores.wild,
            expert_score=peak_scores.expert,
        ),
        PeakSeasonRankSummary.empty(),
        extra_errors,
        on_error=_log_player_extra_error,
    )
    autocard_rank_summary = await optional_player_extra(
        "群星牌排行",
        fetch_plan.needs_autocard_rank,
        lambda: fetch_autocard_rank_summary(game, player_id),
        RankLookupResult(title="群星之巅榜", score_name="分"),
        extra_errors,
        on_error=_log_player_extra_error,
    )
    local_rank_summary = await optional_player_extra(
        "机器人查询排行",
        fetch_plan.needs_local_rank,
        lambda: update_local_rank_cache(
            player_id=player_id,
            nick=user_info.nick,
            more_info=more_info,
            unity_part_one=unity_part_one,
            unity_peak=unity_peak,
            rank_summary=rank_summary,
            autocard_rank_summary=autocard_rank_summary,
            peak_sub_key=peak_sub_key,
            peak_standard_score=peak_scores.standard,
            peak_wild_score=peak_scores.wild,
            peak_expert_score=peak_scores.expert,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_player_extra_error,
    )
    return format_player_detail_messages(
        player_id=player_id,
        user_info=user_info,
        more_info=more_info,
        unity_part_one=unity_part_one,
        unity_peak=unity_peak,
        rank_summary=rank_summary,
        peak_rank_summary=peak_rank_summary,
        autocard_rank_summary=autocard_rank_summary,
        local_rank_summary=local_rank_summary,
        empty_local_rank_summary=LocalRankSummary(),
        has_collection=has_collection,
        needs_peak_section=needs_peak_section,
        has_autocard_rank=has_autocard_rank,
        show_local_rank=show_local_rank,
        extra_errors=extra_errors,
    )
