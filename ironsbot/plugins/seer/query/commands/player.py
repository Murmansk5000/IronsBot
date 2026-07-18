# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from dataclasses import dataclass
from typing import Any

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
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.services.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.packets import ensure_extended_packets
from ironsbot.services.seer.player_binding import (
    bind_player,
    decline_player_binding,
    get_player_binding,
    parse_binding_choice,
    parse_player_binding_target,
    player_binding_offer_message,
    unbind_player,
)
from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_query import (
    PlayerQuerySectionPlan,
    extract_player_query_arg,
    optional_player_extra,
    plan_player_query_sections,
    player_query_failure_message,
    player_query_timeout_message,
)
from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
from ironsbot.services.seer.sequ_extra import (
    UnityPeakInfo,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    enter_event_reply_conversation,
    finish_event_reply,
)
from ironsbot.utils.rule import BOT_COMMAND_ARG_KEY, no_reply

from ..config import (
    get_local_rank_config,
    get_player_query_config,
    get_team_query_config,
)
from ..group import SeerMatcherGroup, seer_feature_rule
from ._args import parse_numeric_id
from .player_context import (
    PLAYER_BINDING_COMMAND_ID_KEY,
    PLAYER_BINDING_NAMESPACE,
    PLAYER_BINDING_PENDING_KEY,
    PLAYER_ID_KEY,
    PLAYER_QUERY_IS_EXPLICIT_KEY,
)
from .player_detail_conversation import (
    send_player_info_with_detail_prompt,
)
from .player_detail_fetch import create_player_detail_task

_MAX_PLAYER_ID = 2_000_000_000


@dataclass(slots=True)
class PendingPlayerQuery:
    player_id: int
    user_info: Any
    more_info: Any
    player_message: str
    section_plan: PlayerQuerySectionPlan


async def _is_player_id_query(event: Event, state: T_State) -> bool:
    arg = extract_player_query_arg(event.get_plaintext())
    if arg is None:
        return False

    if not arg:
        state[PLAYER_QUERY_IS_EXPLICIT_KEY] = False
        return True
    if not arg.isdigit():
        return False

    state[BOT_COMMAND_ARG_KEY] = arg
    state[PLAYER_QUERY_IS_EXPLICIT_KEY] = True
    return True


async def _is_invalid_player_text_query(event: Event) -> bool:
    arg = extract_player_query_arg(event.get_plaintext())
    return arg is not None and bool(arg) and not arg.isdigit()


async def _is_binding_command(event: Event, state: T_State) -> bool:
    player_id = parse_player_binding_target(event.get_plaintext())
    if player_id is None:
        return False
    state[PLAYER_BINDING_COMMAND_ID_KEY] = player_id
    return True


async def block_invalid_player_text_query() -> None:
    return


def _log_player_extra_error(label: str, _error: Exception) -> None:
    logger.opt(exception=True).warning(f"米米号扩展字段获取失败：{label}")


async def validate_player_id(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    if state.get(PLAYER_QUERY_IS_EXPLICIT_KEY, True):
        player_id = await parse_numeric_id(
            matcher,
            state,
            min_value=1,
            max_value=_MAX_PLAYER_ID,
            error_message="❌ 米米号无效，请输入纯数字米米号。",
        )
    else:
        binding = get_player_binding(
            get_player_query_config().binding.path,
            event.user_id,
        )
        if binding.player_id is None:
            await finish_event_reply(
                matcher,
                event,
                "尚未设置默认米米号，请先发送“米米号+数字”查询。\n"
                "首次成功查询后可以选择是否设为默认米米号。",
                mention_sender=True,
            )
        player_id = binding.player_id
        if player_id is None:
            return
    state[PLAYER_ID_KEY] = player_id


async def handle_player(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    ensure_extended_packets()
    player_id: int = state[PLAYER_ID_KEY]
    player_config = get_player_query_config()
    try:
        pending, game_user_id = await _fetch_pending_player_query(player_id)
        await mark_headless_available(
            source="米米号查询",
            user_id=game_user_id,
        )
    except FinishedException:
        raise
    except (SocketRecvError, NotLoggedInError, DisconnectedError) as e:
        if isinstance(e, (NotLoggedInError, DisconnectedError)):
            await mark_headless_unavailable(str(e), source="米米号查询")
        await finish_event_reply(
            matcher,
            event,
            format_player_query_error(player_id, e),
            mention_sender=True,
        )
        return
    except TimeoutError:
        await finish_event_reply(
            matcher,
            event,
            player_query_timeout_message(player_id),
            mention_sender=True,
        )
        return
    except Exception as e:  # noqa: BLE001
        await finish_event_reply(
            matcher,
            event,
            player_query_failure_message(player_id, e),
            mention_sender=True,
        )
        return

    binding = get_player_binding(player_config.binding.path, event.user_id)
    if state.get(PLAYER_QUERY_IS_EXPLICIT_KEY, True) and not binding.choice_completed:
        state[PLAYER_BINDING_PENDING_KEY] = pending
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=PLAYER_BINDING_NAMESPACE,
            handlers=[handle_player_binding_choice],
            reply_check=lambda reply: parse_binding_choice(reply.get_plaintext())
            is not None,
            prompt=player_binding_offer_message(player_id, pending.user_info.nick),
            mention_sender=True,
        )

    await _send_pending_player_query(matcher, event, state, pending)


async def _fetch_pending_player_query(player_id: int) -> tuple[PendingPlayerQuery, int]:
    extra_errors: list[str] = []
    player_config = get_player_query_config()
    section_plan = plan_player_query_sections(
        player_config.sections,
        local_rank_enabled=get_local_rank_config().enabled,
    )
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

    team_name = "无"
    if getattr(user_info, "team_id", 0) > 0:
        try:
            team_info = await asyncio.wait_for(
                game.get_team_info(user_info.team_id),
                timeout=min(5.0, get_team_query_config().timeout_seconds),
            )
            team_name = team_info.name
        except Exception:  # noqa: BLE001
            team_name = str(user_info.team_id)

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
    return (
        PendingPlayerQuery(
            player_id=player_id,
            user_info=user_info,
            more_info=more_info,
            player_message=player_message,
            section_plan=section_plan,
        ),
        int(game.user_id),
    )


async def handle_player_binding_choice(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    pending = state.get(PLAYER_BINDING_PENDING_KEY)
    if not isinstance(pending, PendingPlayerQuery):
        return

    choice = parse_binding_choice(event.get_plaintext())
    if choice is None:
        return

    status_message = ""
    try:
        if choice:
            bind_player(
                get_player_query_config().binding.path,
                qq_user_id=event.user_id,
                player_id=pending.player_id,
                player_nick=str(pending.user_info.nick),
            )
            status_message = f"已设置默认米米号：{pending.player_id}。"
        else:
            decline_player_binding(
                get_player_query_config().binding.path,
                qq_user_id=event.user_id,
            )
            status_message = "已跳过默认米米号设置。"
    except Exception as error:  # noqa: BLE001
        logger.opt(exception=True).warning("保存米米号绑定选择失败")
        status_message = f"⚠️ 默认米米号设置保存失败：{error}"

    pending.player_message = f"{status_message}\n\n{pending.player_message}"
    await _send_pending_player_query(matcher, event, state, pending)


async def _send_pending_player_query(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    pending: PendingPlayerQuery,
) -> None:
    section_plan = pending.section_plan
    detail_task = (
        create_player_detail_task(
            player_id=pending.player_id,
            user_info=pending.user_info,
            more_info=pending.more_info,
            has_collection=section_plan.has_collection,
            needs_peak_section=section_plan.needs_peak_section,
            has_autocard_rank=section_plan.has_autocard_rank,
            show_local_rank=section_plan.show_local_rank,
        )
        if section_plan.needs_detail_task
        else None
    )
    await send_player_info_with_detail_prompt(
        matcher,
        event,
        state,
        player_message=pending.player_message,
        detail_task=detail_task,
        has_collection=section_plan.has_collection,
        has_peak=section_plan.needs_peak_section,
        has_autocard=section_plan.has_autocard_rank,
    )


async def handle_player_binding_command(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    player_id = int(state[PLAYER_BINDING_COMMAND_ID_KEY])
    if not 1 <= player_id <= _MAX_PLAYER_ID:
        await finish_event_reply(
            matcher,
            event,
            "❌ 米米号无效，请输入纯数字米米号。",
            mention_sender=True,
        )
    ensure_extended_packets()
    try:
        pending, game_user_id = await _fetch_pending_player_query(player_id)
        await mark_headless_available(
            source="米米号绑定",
            user_id=game_user_id,
        )
    except FinishedException:
        raise
    except TimeoutError:
        await finish_event_reply(
            matcher,
            event,
            player_query_timeout_message(player_id),
            mention_sender=True,
        )
        return
    except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
        if isinstance(error, (NotLoggedInError, DisconnectedError)):
            await mark_headless_unavailable(str(error), source="米米号绑定")
        await finish_event_reply(
            matcher,
            event,
            format_player_query_error(player_id, error),
            mention_sender=True,
        )
        return
    except Exception as error:  # noqa: BLE001
        await finish_event_reply(
            matcher,
            event,
            player_query_failure_message(player_id, error),
            mention_sender=True,
        )
        return

    status_message: str
    try:
        bind_player(
            get_player_query_config().binding.path,
            qq_user_id=event.user_id,
            player_id=player_id,
            player_nick=str(pending.user_info.nick),
        )
        status_message = f"已设置默认米米号：{player_id}。"
    except Exception as error:  # noqa: BLE001
        logger.opt(exception=True).warning("保存主动米米号绑定失败")
        status_message = f"⚠️ 默认米米号设置保存失败：{error}"

    pending.player_message = f"{status_message}\n\n{pending.player_message}"
    await _send_pending_player_query(
        matcher,
        event,
        state,
        pending,
    )


async def handle_player_unbind(matcher: Matcher, event: MessageEvent) -> None:
    removed = unbind_player(
        get_player_query_config().binding.path,
        qq_user_id=event.user_id,
    )
    message = "已解除默认米米号。" if removed else "当前没有已绑定的米米号。"
    await finish_event_reply(matcher, event, message, mention_sender=True)


def install(group: SeerMatcherGroup) -> None:
    binding_matcher = group.on_message(
        policy=CommandPolicy.command("seer_player_binding"),
        rule=seer_feature_rule("seer_player")
        & Rule(_is_binding_command)
        & no_reply(),
        priority=get_matcher_priority("seer_player", 1),
        block=True,
    )
    binding_matcher.append_handler(handle_player_binding_command)

    unbind_matcher = group.on_fullmatch(
        ("解绑米米号",),
        policy=CommandPolicy.command("seer_player_binding"),
        rule=seer_feature_rule("seer_player") & no_reply(),
        priority=get_matcher_priority("seer_player", 1),
        block=True,
    )
    unbind_matcher.append_handler(handle_player_unbind)

    invalid_matcher = group.on_message(
        policy=CommandPolicy.exempt("silent invalid player query blocker"),
        rule=seer_feature_rule("seer_player")
        & Rule(_is_invalid_player_text_query)
        & no_reply(),
        priority=get_matcher_priority("seer_player", 1),
        block=True,
    )
    invalid_matcher.append_handler(block_invalid_player_text_query)

    query_matcher = group.on_message(
        policy=CommandPolicy.command("seer_player"),
        rule=seer_feature_rule("seer_player")
        & Rule(_is_player_id_query)
        & no_reply(),
        priority=get_matcher_priority("seer_player", 1),
        block=True,
    )
    query_matcher.append_handler(validate_player_id)
    query_matcher.append_handler(handle_player)


__all__ = ["install"]
