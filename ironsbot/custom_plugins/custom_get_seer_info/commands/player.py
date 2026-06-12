# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.custom_plugins.message_actions import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.plugins.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.local_rank import LocalRankSummary, update_local_rank_cache
from ironsbot.services.seer.packets import ensure_extended_packets
from ironsbot.services.seer.player_formatting import (
    append_extra_errors,
    format_collection_info,
    format_compact_peak_section,
    format_compact_player_info,
    format_player_identity,
)
from ironsbot.services.seer.player_query import (
    PlayerDetailMessages,
    extract_player_query_arg,
    plan_player_query_sections,
    player_detail_commands,
    player_detail_pending_message,
    player_query_in_progress_message,
    player_query_wait_message,
)
from ironsbot.services.seer.rank import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    build_peak_rating_score,
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
    get_current_peak_sub_key,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)
from ironsbot.shared.messaging.conversations import command_reply_check
from ironsbot.shared.messaging.query_guard import QueryGuard
from ironsbot.shared.messaging.text import command_text_matches
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import BOT_COMMAND_ARG_KEY, no_reply

from ..config import (
    get_local_rank_config,
    get_player_query_config,
    get_team_query_config,
)
from ..group import matcher_group
from ._args import parse_numeric_id

PLAYER_ID_KEY = "player_id"
PLAYER_COLLECTION_KEY = "_player_collection_message"
PLAYER_PEAK_KEY = "_player_peak_message"
PLAYER_DETAIL_TASK_KEY = "_player_detail_task"
PLAYER_DETAIL_COMMANDS_KEY = "_player_detail_commands"
PLAYER_DETAIL_AUTO_REPLY_KEYS = "_player_detail_auto_reply_keys"
PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY = "_player_detail_auto_reply_tasks"
PLAYER_DETAIL_NAMESPACE = "custom_get_seer_info_player_details"
PLAYER_PLUGIN_NAME = "seer_player"
PLAYER_QUERY_GUARD = QueryGuard(
    success_namespace="custom_get_seer_info.player_query.success",
    failure_namespace="custom_get_seer_info.player_query.failure",
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
    rule=Rule(_is_invalid_player_text_query) & no_reply(),
    priority=1,
    block=True,
)

player_matcher = matcher_group.on_message(
    rule=Rule(_is_player_id_query) & no_reply(),
    priority=1,
    block=True,
)


@player_invalid_text_matcher.handle()
async def block_invalid_player_text_query() -> None:
    return



async def _safe_extra(
    label: str,
    coro: Any,
    default: Any,
    extra_errors: list[str],
) -> Any:
    try:
        return await coro
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning(f"米米号扩展字段获取失败：{label}")
        extra_errors.append(f"{label}失败：{e}")
        return default


async def _optional_extra(
    label: str,
    enabled: bool,  # noqa: FBT001
    coro_factory: Callable[[], Any],
    default: Any,
    extra_errors: list[str],
) -> Any:
    if not enabled:
        return default

    return await _safe_extra(label, coro_factory(), default, extra_errors)


class PlayerQueryPlugin:
    name = PLAYER_PLUGIN_NAME
    feature = "seer"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        state = context.state if context.state is not None else {}
        if context.action == "validate":
            await self._validate_player_id(matcher, event, state)
            return
        if context.action == "detail_reply":
            await self._handle_detail_reply(matcher, event, state)
            return
        if context.action == "query":
            await self._handle_player(matcher, event, state)

    async def _validate_player_id(
        self,
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

    async def _handle_detail_reply(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        text = event.get_plaintext()
        if command_text_matches(text, ("收集",)):
            label = "收集与排行"
            message = await _get_player_detail_message(
                state,
                PLAYER_COLLECTION_KEY,
                label,
                matcher=matcher,
                event=event,
            )
        elif command_text_matches(text, ("巅峰",)):
            label = "巅峰之战"
            message = await _get_player_detail_message(
                state,
                PLAYER_PEAK_KEY,
                label,
                matcher=matcher,
                event=event,
            )
        else:
            message = None

        if not message:
            raise FinishedException

        await _continue_player_detail_conversation(
            matcher,
            event,
            state,
            prompt=message,
        )

    async def _handle_player(
        self,
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
            user_info, more_info, online_info = await asyncio.wait_for(
                asyncio.gather(
                    game.get_user_info(player_id),
                    game.get_more_user_info(player_id),
                    _optional_extra(
                        "在线状态",
                        section_plan.needs_online_info,
                        lambda: game.get_user_online_info(player_id),
                        None,
                        extra_errors,
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
                detail_task = _create_player_detail_task(
                    player_id=player_id,
                    user_info=user_info,
                    more_info=more_info,
                    has_collection=section_plan.has_collection,
                    needs_peak_section=section_plan.needs_peak_section,
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
                f"❌ 米米号 {player_id} 查询超时，请稍后再试。",
                mention_sender=True,
            )
            return
        except Exception as e:  # noqa: BLE001
            PLAYER_QUERY_GUARD.clear_in_progress(event.user_id)
            PLAYER_QUERY_GUARD.penalize_failure(event.user_id)
            await finish_event_reply(
                matcher,
                event,
                f"❌ 米米号 {player_id} 查询失败：{e}",
                mention_sender=True,
            )
            return

        PLAYER_QUERY_GUARD.clear_in_progress(event.user_id)
        PLAYER_QUERY_GUARD.penalize_success(event.user_id)
        await _send_player_info_with_detail_prompt(
            matcher,
            event,
            state,
            player_message=player_message,
            detail_task=detail_task,
            has_collection=section_plan.has_collection,
            has_peak=section_plan.needs_peak_section,
        )


register_plugin(PlayerQueryPlugin())


@player_matcher.handle()
async def validate_player_id(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=PLAYER_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="validate",
    )


async def _handle_detail_reply(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=PLAYER_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="detail_reply",
    )


def _store_player_detail_messages(
    state: T_State,
    detail_messages: PlayerDetailMessages,
) -> None:
    state[PLAYER_COLLECTION_KEY] = detail_messages.collection_message
    state[PLAYER_PEAK_KEY] = detail_messages.peak_message


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
            return f"❌ {label}数据查询超时，请稍后再试。"
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as e:
            state[PLAYER_DETAIL_TASK_KEY] = None
            return format_player_query_error(int(state.get(PLAYER_ID_KEY, 0)), e)
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).warning("米米号后台详情任务失败")
            state[PLAYER_DETAIL_TASK_KEY] = None
            return f"❌ {label}数据获取失败：{e}"

        _store_player_detail_messages(state, detail_messages)
        state[PLAYER_DETAIL_TASK_KEY] = None

    return str(state.get(key) or "")


def _auto_reply_keys(state: T_State) -> set[str]:
    raw_keys = state.get(PLAYER_DETAIL_AUTO_REPLY_KEYS)
    if isinstance(raw_keys, set):
        return raw_keys

    keys: set[str] = set()
    state[PLAYER_DETAIL_AUTO_REPLY_KEYS] = keys
    return keys


def _auto_reply_tasks(state: T_State) -> set[asyncio.Task[None]]:
    raw_tasks = state.get(PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY)
    if isinstance(raw_tasks, set):
        return raw_tasks

    tasks: set[asyncio.Task[None]] = set()
    state[PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY] = tasks
    return tasks


def _schedule_player_detail_auto_reply(  # noqa: PLR0913
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    key: str,
    label: str,
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    auto_reply_keys = _auto_reply_keys(state)
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
    auto_reply_tasks = _auto_reply_tasks(state)
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
            message = f"❌ {label}数据没有返回结果，请稍后再试。"

        await send_event_reply(
            matcher,
            event,
            message,
            mention_sender=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"米米号后台详情自动回复失败：{e}")
    finally:
        _auto_reply_keys(state).discard(key)


async def _continue_player_detail_conversation(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    prompt: str,
) -> None:
    commands = tuple(state.get(PLAYER_DETAIL_COMMANDS_KEY) or ())
    if not commands:
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
        handlers=[_handle_detail_reply],
        reply_check=command_reply_check(commands),
        prompt=prompt,
        mention_sender=True,
    )


async def _send_player_info_with_detail_prompt(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    player_message: str,
    detail_task: asyncio.Task[PlayerDetailMessages] | None = None,
    has_collection: bool = False,
    has_peak: bool = False,
) -> None:
    commands = player_detail_commands(
        has_collection=has_collection,
        has_peak=has_peak,
    )

    if detail_task is not None:
        state[PLAYER_DETAIL_TASK_KEY] = detail_task

    state[PLAYER_DETAIL_COMMANDS_KEY] = commands

    if not commands:
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
        handlers=[_handle_detail_reply],
        reply_check=command_reply_check(tuple(commands)),
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


def _create_player_detail_task(  # noqa: PLR0913
    *,
    player_id: int,
    user_info: Any,
    more_info: Any,
    has_collection: bool,
    needs_peak_section: bool,
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
    show_local_rank: bool,
) -> PlayerDetailMessages:
    game = get_game_client()
    extra_errors: list[str] = []
    needs_local_rank = get_local_rank_config().enabled
    needs_unity_part_one = has_collection
    needs_unity_peak = needs_peak_section
    needs_rank_summary = has_collection or needs_local_rank

    if needs_local_rank:
        needs_unity_part_one = True
        needs_unity_peak = True

    unity_part_one, unity_peak = await asyncio.gather(
        _optional_extra(
            "展示/收集数据",
            needs_unity_part_one,
            lambda: fetch_unity_part_one(game, player_id),
            UnityPartOneInfo(),
            extra_errors,
        ),
        _optional_extra(
            "巅峰数据",
            needs_unity_peak,
            lambda: fetch_unity_peak(game, player_id),
            UnityPeakInfo(),
            extra_errors,
        ),
    )
    rank_summary = await _optional_extra(
        "全服排行",
        needs_rank_summary,
        lambda: fetch_player_rank_summary(
            game,
            player_id,
            achieve_score=getattr(more_info, "total_achieve", None),
            pet_kind_count=unity_part_one.pet_kind_num,
            skin_score=unity_part_one.skin_num,
        ),
        PlayerRankSummary.empty(),
        extra_errors,
    )
    peak_sub_key = get_current_peak_sub_key()
    peak_standard_score = (
        build_peak_rating_score(
            unity_peak.current_j_rank,
            unity_peak.current_j_star,
        )
        if unity_peak.current_j_all > 0
        else None
    )
    peak_wild_score = (
        build_peak_rating_score(
            unity_peak.current_k_rank,
            unity_peak.current_k_star,
        )
        if unity_peak.current_k_all > 0
        else None
    )
    peak_expert_score = (
        unity_peak.current_z_score
        if unity_peak.current_z_all > 0
        else None
    )
    peak_rank_summary = await _optional_extra(
        "巅峰赛季榜",
        needs_peak_section,
        lambda: fetch_peak_season_rank_summary(
            game,
            player_id,
            standard_score=peak_standard_score,
            wild_score=peak_wild_score,
            expert_score=peak_expert_score,
        ),
        PeakSeasonRankSummary.empty(),
        extra_errors,
    )
    local_rank_summary = await _optional_extra(
        "机器人查询排行",
        needs_local_rank,
        lambda: update_local_rank_cache(
            player_id=player_id,
            nick=user_info.nick,
            more_info=more_info,
            unity_part_one=unity_part_one,
            unity_peak=unity_peak,
            rank_summary=rank_summary,
            peak_sub_key=peak_sub_key,
            peak_standard_score=peak_standard_score,
            peak_wild_score=peak_wild_score,
            peak_expert_score=peak_expert_score,
        ),
        LocalRankSummary(),
        extra_errors,
    )
    visible_local_rank_summary = (
        local_rank_summary if show_local_rank else LocalRankSummary()
    )

    collection_message = (
        format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=visible_local_rank_summary,
            player_identity=format_player_identity(player_id, user_info.nick),
        )
        if has_collection
        else ""
    )
    peak_message = (
        format_compact_peak_section(
            unity_peak,
            peak_rank_summary,
            visible_local_rank_summary,
            player_id=player_id,
            nick=user_info.nick,
        )
        if needs_peak_section
        else ""
    )
    return PlayerDetailMessages(
        collection_message=append_extra_errors(collection_message, extra_errors)
        if collection_message
        else "",
        peak_message=append_extra_errors(peak_message, extra_errors)
        if peak_message
        else "",
    )


@player_matcher.handle()
async def handle_player(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=PLAYER_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="query",
    )
