# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.common.query_guard import QueryGuard
from ironsbot.custom_plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.custom_plugins.message_actions import (
    command_reply_check,
    command_text_matches,
    enter_event_reply_conversation,
    finish_event_reply,
)
from ironsbot.plugins.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.utils.rule import BOT_COMMAND_ARG_KEY, no_reply

from ..config import plugin_config
from ..group import matcher_group
from ..packets import ensure_extended_packets
from ._args import parse_numeric_id
from ._client import get_game_client
from ._errors import format_player_query_error
from ._format import format_datetime, yes_no
from ._local_rank import LocalRankSummary, update_local_rank_cache
from ._rank import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    build_peak_rating_score,
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
    get_current_peak_sub_key,
)
from ._sequ_extra import (
    UnityPartOneInfo,
    UnityPartTwoInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)

PLAYER_ID_KEY = "player_id"
PLAYER_COLLECTION_KEY = "_player_collection_message"
PLAYER_PEAK_KEY = "_player_peak_message"
PLAYER_DETAIL_TASK_KEY = "_player_detail_task"
PLAYER_DETAIL_COMMANDS_KEY = "_player_detail_commands"
METRIC_SEPARATOR = "\uFF5C"
PLAYER_QUERY_PREFIXES = ("查询玩家信息", "米米号")
PLAYER_DETAIL_NAMESPACE = "custom_get_seer_info_player_details"
QUERY_CONFIG = plugin_config.seer_query_config
PLAYER_QUERY_GUARD = QueryGuard(
    success_namespace="custom_get_seer_info.player_query.success",
    failure_namespace="custom_get_seer_info.player_query.failure",
    success_cooldown=lambda: QUERY_CONFIG.player.rate_limit_seconds,
    failure_cooldown=lambda: QUERY_CONFIG.player.failure_rate_limit_seconds,
)


@dataclass(slots=True)
class PlayerDetailMessages:
    collection_message: str = ""
    peak_message: str = ""


def _extract_player_arg(text_value: str) -> str | None:
    stripped = text_value.strip()
    folded = stripped.casefold()
    for prefix in PLAYER_QUERY_PREFIXES:
        if folded.startswith(prefix.casefold()):
            return stripped[len(prefix) :].strip()
    return None


async def _is_player_id_query(event: Event, state: T_State) -> bool:
    arg = _extract_player_arg(event.get_plaintext())
    if arg is None or not arg.isdigit():
        return False

    state[BOT_COMMAND_ARG_KEY] = arg
    return True


async def _is_invalid_player_text_query(event: Event) -> bool:
    arg = _extract_player_arg(event.get_plaintext())
    return arg is not None and not arg.isdigit()


def _player_query_in_progress_message(player_id: int) -> str:
    return (
        f"⏳ 正在查询米米号 {player_id}，请等当前查询完成。\n"
        "米米号查询需要连接游戏服务器；收集、巅峰和全服排行数据会更慢，"
        "排名越靠后可能查得越久，多人同时查询时也可能需要排队。"
    )


def _player_detail_pending_message(label: str) -> str:
    return (
        f"⏳ {label}还在查询中，请稍等后再试。\n"
        "这部分需要拉取收集、全服榜或赛季榜数据，排名越靠后可能越慢，"
        "多人同时查询时也可能需要排队。"
    )


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


PEAK_RANK_NAMES = {
    0: "学徒",
    1: "猛将",
    2: "天骄",
    3: "王者",
    4: "圣皇",
    5: "宇宙圣皇",
}


def _filter_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if line == "" and (not result or result[-1] == ""):
            continue
        result.append(line)

    while result and result[-1] == "":
        result.pop()

    return result


def _format_id_name(item_id: int, names: dict[int, str]) -> str:
    if item_id <= 0:
        return "无"

    name = names.get(item_id)
    if not name:
        return str(item_id)

    return f"{name}（{item_id}）"


def _format_id_name_list(ids: tuple[int, ...], names: dict[int, str]) -> str:
    items = [_format_id_name(item_id, names) for item_id in ids if item_id > 0]
    return "、".join(items) if items else "无"


def _format_team_text(user_info: Any, team_name: str) -> str:
    team_id = getattr(user_info, "team_id", 0)
    if team_id <= 0:
        return "未加入"

    show_text = "展示" if getattr(user_info, "team_is_show", False) else "隐藏"
    return f"{team_name}（战队ID：{team_id}，{show_text}）"


def _format_player_identity(
    player_id: int,
    nick: str | None = None,
) -> str:
    if nick:
        return f"米米号：{player_id}（{nick}）"
    return f"米米号：{player_id}"


def _format_online_text(online_info: Any | None) -> str:
    if online_info is None:
        return "离线"

    return (
        "在线"
        f"（服务器：{online_info.server_id}，"
        f"地图类型：{online_info.map_type}，地图ID：{online_info.map_id}）"
    )


def _format_status(value: int) -> str:
    if value == 1:
        return "正常"
    if value == 0:
        return "未知"
    return f"状态值：{value}"


def _format_vip(user_info: Any) -> str:
    if getattr(user_info, "vip", 0):
        return f"是（等级：{getattr(user_info, 'vip_level', 0)}）"
    return "否"


def _format_rank_star(rank: int, star: int) -> str:
    name = PEAK_RANK_NAMES.get(rank, f"段位{rank}")
    return f"{name}（{star}星）"


def _format_rank_star_compact(rank: int, star: int) -> str:
    name = PEAK_RANK_NAMES.get(rank, f"段位{rank}")
    return f"{name}{star}星"


def _format_win_rate(wins: int, total: int) -> str:
    if total <= 0:
        return "当前赛季未参赛"

    return f"{wins}/{total}={wins / total * 100:.3f}%"


def _join_metric_parts(*parts: str) -> str:
    return METRIC_SEPARATOR.join(part for part in parts if part)


def _rank_lookup_text(result: RankLookupResult | None) -> str:
    if result is None:
        return ""
    if result.rank is not None:
        return f"全服第{result.rank}"
    if result.queried and result.searched_limit > 0:
        return f"全服未进入前{result.searched_limit}"
    return ""


def _sample_rank_text(summary: LocalRankSummary, key: str) -> str:
    return summary.sample_rank(key)


def _format_metric_line(
    title: str,
    value: int | None,
    *,
    rank_result: RankLookupResult | None = None,
    local_summary: LocalRankSummary,
    local_key: str,
) -> str | None:
    value_text = str(value) if value is not None and value >= 0 else "暂无数据"

    metric_text = _join_metric_parts(
        value_text,
        _rank_lookup_text(rank_result),
        _sample_rank_text(local_summary, local_key),
    )
    return f"{title}：{metric_text}"


def _format_peak_rank_text(rank: int | None) -> str:
    return f"赛季榜第{rank}" if rank is not None else "赛季榜未上榜"


def _format_local_rank_suffix(
    summary: LocalRankSummary,
    key: str,
    *,
    label: str = "样本",
) -> str:
    text = summary.sample_rank(key)
    if not text:
        return ""

    if text.startswith("样本"):
        text = f"{label}{text.removeprefix('样本')}"
    return f"（{text}）"


def _format_peak_line(  # noqa: PLR0913
    title: str,
    *,
    current: str,
    history: str,
    match_count: int,
    win_rate: str,
    rank: int | None,
    local_summary: LocalRankSummary,
    score_key: str,
    win_rate_key: str,
    match_key: str,
) -> str:
    match_text = ""
    if match_count > 0:
        match_text = (
            f"场次{match_count}"
            f"{_format_local_rank_suffix(local_summary, match_key, label='样本场次')}"
        )
    win_rate_text = (
        f"胜率{win_rate}"
        f"{_format_local_rank_suffix(local_summary, win_rate_key, label='样本胜率')}"
    )
    rank_text = (
        f"{_format_peak_rank_text(rank)}"
        f"{_format_local_rank_suffix(local_summary, score_key, label='样本段位')}"
    )
    return (
        f"{title}：{current}{METRIC_SEPARATOR}历史{history}"
        f"{METRIC_SEPARATOR}"
        f"{_join_metric_parts(match_text, win_rate_text, rank_text)}"
    )


def _format_compact_peak_section(
    peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    *,
    player_id: int | None = None,
    nick: str | None = None,
) -> str:
    lines = ["【巅峰之战】"]
    if player_id is not None:
        lines.append(_format_player_identity(player_id, nick))

    lines.extend(
        [
            _format_peak_line(
                "竞技",
                current=_format_rank_star_compact(
                    peak.current_j_rank,
                    peak.current_j_star,
                ),
                history=_format_rank_star_compact(
                    peak.history_j_rank,
                    peak.history_j_star,
                ),
                match_count=peak.current_j_all,
                win_rate=_format_win_rate(
                    peak.current_j_win,
                    peak.current_j_all,
                ),
                rank=peak_rank_summary.standard.rank,
                local_summary=local_summary,
                score_key="peak_standard",
                win_rate_key="peak_standard_win_rate",
                match_key="peak_standard_matches",
            ),
            _format_peak_line(
                "狂野",
                current=_format_rank_star_compact(
                    peak.current_k_rank,
                    peak.current_k_star,
                ),
                history=_format_rank_star_compact(
                    peak.history_k_rank,
                    peak.history_k_star,
                ),
                match_count=peak.current_k_all,
                win_rate=_format_win_rate(
                    peak.current_k_win,
                    peak.current_k_all,
                ),
                rank=peak_rank_summary.wild.rank,
                local_summary=local_summary,
                score_key="peak_wild",
                win_rate_key="peak_wild_win_rate",
                match_key="peak_wild_matches",
            ),
            _format_peak_line(
                "专家",
                current=f"{peak.current_z_score}分",
                history=f"{peak.history_z_score}分",
                match_count=peak.current_z_all,
                win_rate=_format_win_rate(
                    peak.current_z_win,
                    peak.current_z_all,
                ),
                rank=peak_rank_summary.expert.rank,
                local_summary=local_summary,
                score_key="peak_expert",
                win_rate_key="peak_expert_win_rate",
                match_key="peak_expert_matches",
            ),
        ]
    )
    return "\n".join(
        lines
    )


def _format_collection_info(
    more_info: Any,
    *,
    unity_part_one: UnityPartOneInfo,
    rank_summary: PlayerRankSummary,
    local_summary: LocalRankSummary,
    player_identity: str,
) -> str:
    breakdown = rank_summary.breakdown
    outfit_suit_score = (
        None if breakdown.outfit_suit is None else breakdown.outfit_suit.score
    )
    outfit_part_score = (
        None if breakdown.outfit_part is None else breakdown.outfit_part.score
    )
    countermark_score = (
        None if breakdown.countermark is None else breakdown.countermark.score
    )

    metric_lines = [
        _format_metric_line(
            "精灵数量",
            getattr(more_info, "pet_all_num", 0),
            local_summary=local_summary,
            local_key="pet_total_count",
        ),
        _format_metric_line(
            "图鉴积分",
            rank_summary.book.score,
            rank_result=rank_summary.book,
            local_summary=local_summary,
            local_key="book_score",
        ),
        _format_metric_line(
            "成就点数",
            getattr(more_info, "total_achieve", 0),
            rank_result=rank_summary.achieve,
            local_summary=local_summary,
            local_key="achievement_score",
        ),
        _format_metric_line(
            "精灵图鉴",
            unity_part_one.pet_kind_num,
            rank_result=breakdown.pet_kind,
            local_summary=local_summary,
            local_key="pet_kind_count",
        ),
        _format_metric_line(
            "皮肤图鉴",
            unity_part_one.skin_num,
            rank_result=breakdown.skin,
            local_summary=local_summary,
            local_key="skin_count",
        ),
        _format_metric_line(
            "套装图鉴",
            outfit_suit_score,
            rank_result=breakdown.outfit_suit,
            local_summary=local_summary,
            local_key="outfit_suit_count",
        ),
        _format_metric_line(
            "部件图鉴",
            outfit_part_score,
            rank_result=breakdown.outfit_part,
            local_summary=local_summary,
            local_key="outfit_part_count",
        ),
        _format_metric_line(
            "座驾图鉴",
            None if breakdown.mount is None else breakdown.mount.score,
            rank_result=breakdown.mount,
            local_summary=local_summary,
            local_key="mount_count",
        ),
        _format_metric_line(
            "刻印图鉴",
            countermark_score,
            rank_result=breakdown.countermark,
            local_summary=local_summary,
            local_key="countermark_count",
        ),
        _format_metric_line(
            "已解锁图鉴条目",
            breakdown.unlocked_count,
            local_summary=local_summary,
            local_key="unlocked_book_entries",
        ),
        _format_metric_line(
            "成就数量",
            unity_part_one.achievement_num,
            local_summary=local_summary,
            local_key="achievement_count",
        ),
    ]
    lines = ["📚【收集与排行】", player_identity]
    lines.extend(line for line in metric_lines if line)
    return "\n".join(lines)


def _format_compact_player_info(  # noqa: PLR0913
    user_info: Any,
    more_info: Any,
    *,
    team_name: str,
    online_info: Any | None,
    unity_peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    has_collection: bool,
    has_peak: bool,
    show_peak: bool,
    extra_errors: list[str],
) -> str:
    lines = [
        "🤖【玩家信息】",
        f"米米号：{user_info.user_id}（{user_info.nick}）",
        "",
        "【基础信息】",
        f"昵称：{user_info.nick}",
        f"VIP状态：{_format_vip(user_info)}",
        f"注册时间：{format_datetime(getattr(more_info, 'reg_time', 0))}",
        f"最后登录：{format_datetime(getattr(user_info, 'login_time', 0))}",
        f"最后离线：{format_datetime(getattr(user_info, 'last_offline_time', 0))}",
        f"是否在线：{_format_online_text(online_info)}",
        "",
        f"战队：{_format_team_text(user_info, team_name)}",
    ]

    if show_peak:
        lines.extend(
            (
                "",
                _format_compact_peak_section(
                    unity_peak,
                    peak_rank_summary,
                    local_summary,
                ),
            )
        )

    if has_collection:
        lines.extend(("", "回复“收集”查看收集与排行"))

    if has_peak and not show_peak:
        lines.extend(("", "回复“巅峰”查看巅峰之战"))

    if extra_errors:
        lines.extend(("", "【扩展数据提示】", "；".join(extra_errors)))

    return "\n".join(_filter_blank_lines(lines))


def _format_hidden_player_details(  # noqa: PLR0913
    user_info: Any,
    more_info: Any,
    *,
    unity_part_one: UnityPartOneInfo,
    unity_part_two: UnityPartTwoInfo,
    title_names: dict[int, str],
    pet_names: dict[int, str],
    equip_names: dict[int, str],
) -> str:
    clothes = tuple(getattr(user_info, "clothes", ()))
    decorate = tuple(getattr(user_info, "decorate_list", ()))
    boss_flags = tuple(getattr(more_info, "boss_achievement", ()))
    boss_count = sum(1 for flag in boss_flags if flag)

    lines = [
        "【隐藏详情】",
        f"至尊NONO：{yes_no(getattr(user_info, 'is_extreme_nono', False))}",
        f"账号状态：{_format_status(getattr(user_info, 'status', 0))}",
        f"当前称号：{_format_id_name(getattr(more_info, 'cur_title', 0), title_names)}",
        f"头像ID：{getattr(user_info, 'head_id', 0)}",
        f"头像框ID：{getattr(user_info, 'head_frame_id', 0)}",
        f"昵称背景ID：{getattr(user_info, 'nick_bg', 0)}",
        f"装备：{_format_id_name_list(clothes, equip_names)}",
        f"幻化/装饰：{_format_id_name_list(decorate, equip_names)}",
        f"可成为教官：{yes_no(getattr(user_info, 'is_can_be_teacher', False))}",
        f"老师米米号：{getattr(user_info, 'teacher_id', 0) or '无'}",
        f"学生米米号：{getattr(user_info, 'student_id', 0) or '无'}",
        f"毕业学员数：{getattr(more_info, 'graduation_count', 0)}",
        f"机器人好友：{yes_no(getattr(user_info, 'is_friend', False))}",
        f"机器人黑名单：{yes_no(getattr(user_info, 'is_black', False))}",
        f"最高精灵等级：{getattr(more_info, 'pet_max_lev', 0)}",
        f"成就闪耀值：{getattr(more_info, 'achie_shine', 0)}",
        f"Boss成就：{boss_count}/{len(boss_flags) or 199}",
        f"称号1：{_format_id_name(unity_part_one.title1, title_names)}",
        f"称号2：{_format_id_name(unity_part_one.title2, title_names)}",
        f"称号3：{_format_id_name(unity_part_one.title3, title_names)}",
        f"称号4：{_format_id_name(unity_part_one.title4, title_names)}",
        f"精灵1：{_format_id_name(unity_part_two.show_pet1, pet_names)}",
        f"精灵2：{_format_id_name(unity_part_two.show_pet2, pet_names)}",
        f"精灵3：{_format_id_name(unity_part_two.show_pet3, pet_names)}",
        f"精灵4：{_format_id_name(unity_part_two.show_pet4, pet_names)}",
        f"试炼之塔：{getattr(more_info, 'max_fresh_stage', 0)}层",
        f"勇者之塔：{getattr(more_info, 'max_stage', 0)}层",
        f"王者之塔：{getattr(more_info, 'max_king_stage', 0)}层",
        f"王者英雄塔：{getattr(more_info, 'max_king_hero_stage', 0)}层",
        f"战斗阶梯：{getattr(more_info, 'max_ladder_state', 0)}层",
        f"命运之轮：{getattr(more_info, 'max_fortune_state', 0)}层",
        f"高阶战斗：{getattr(more_info, 'high_fight_win', 0)}",
        f"极限法则：{getattr(more_info, 'extreme_law_level', 0)}",
        f"作战实验室：{getattr(more_info, 'battle_lab_info', 0)}",
        f"精灵王之战：{getattr(more_info, 'mon_king_win', 0)}胜",
        f"老巅峰胜负：{getattr(more_info, 'top_win_count', 0)}胜/"
        f"{getattr(more_info, 'top_loss_count', 0)}负",
        f"精灵大乱斗：{getattr(more_info, 'mess_win', 0)}胜",
        f"幸运大作战：{getattr(more_info, 'lucky_fight_win', 0)}胜",
        f"圣地角斗场：{getattr(more_info, 'fight_arena_win', 0)}胜",
        f"精灵大逃杀：{getattr(more_info, 'royale_win', 0)}胜",
        f"暗黑武道场：{getattr(more_info, 'dark_fight_win', 0)}胜",
        f"星际/星空擂台：{getattr(more_info, 'max_space_arena_wins', 0)}",
        f"折光幻阵：{getattr(more_info, 'zheguang_win_times', 0)}胜",
        f"梦幻大乱斗：{getattr(more_info, 'dream_mess_wins', 0)}胜",
        f"课堂胜场：{getattr(more_info, 'total_class_wins', 0)}",
        f"战队Boss字段：{getattr(more_info, 'team_boss', 0)}",
        f"训练师之门：{getattr(more_info, 'trainer_door_num', 0)}",
        f"嘉年华总分：{getattr(more_info, 'carnival_total_score', 0)}",
        f"跨栏胜负：{getattr(more_info, 'hurdles_win_num', 0)}胜/"
        f"{getattr(more_info, 'hurdles_lose_num', 0)}负",
        f"拔河胜负平：{getattr(more_info, 'tug_win_num', 0)}胜/"
        f"{getattr(more_info, 'tug_lose_num', 0)}负/"
        f"{getattr(more_info, 'tug_draw_num', 0)}平",
        f"跳跃次数：{getattr(more_info, 'jump_num', 0)}",
        f"阿瑞斯联盟队伍字段：{getattr(more_info, 'ares_union_team', 0)}",
    ]
    return "\n".join(_filter_blank_lines(lines))


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
            _player_query_in_progress_message(in_progress_player_id),
            mention_sender=True,
        )

    remaining = PLAYER_QUERY_GUARD.remaining_seconds(event.user_id)
    if remaining > 0:
        await finish_event_reply(
            matcher,
            event,
            (
                f"⏳ 刚刚已经发起过米米号查询，请 {remaining} 秒后再试。\n"
                "收集、巅峰和全服排行数据会更慢，排名越靠后可能查得越久，"
                "多人同时查询时也可能需要排队。"
            ),
            mention_sender=True,
        )
    PLAYER_QUERY_GUARD.set_in_progress(event.user_id, player_id)


async def _handle_detail_reply(
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
        )
    elif command_text_matches(text, ("巅峰",)):
        label = "巅峰之战"
        message = await _get_player_detail_message(
            state,
            PLAYER_PEAK_KEY,
            label,
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
) -> str:
    task = state.get(PLAYER_DETAIL_TASK_KEY)
    if isinstance(task, asyncio.Task):
        if not task.done():
            return _player_detail_pending_message(label)

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
    commands: list[str] = []

    if detail_task is not None:
        state[PLAYER_DETAIL_TASK_KEY] = detail_task

    if has_collection:
        commands.append("收集")

    if has_peak:
        commands.append("巅峰")

    state[PLAYER_DETAIL_COMMANDS_KEY] = tuple(commands)

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


def _append_extra_errors(message: str, extra_errors: list[str]) -> str:
    if not extra_errors:
        return message

    return "\n\n".join((message, "【扩展数据提示】", "；".join(extra_errors)))


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
            timeout=plugin_config.seer_query_config.player.detail_timeout_seconds,
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
    needs_local_rank = plugin_config.seer_query_config.local_rank.enabled
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
        _format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=visible_local_rank_summary,
            player_identity=_format_player_identity(player_id, user_info.nick),
        )
        if has_collection
        else ""
    )
    peak_message = (
        _format_compact_peak_section(
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
        collection_message=_append_extra_errors(collection_message, extra_errors)
        if collection_message
        else "",
        peak_message=_append_extra_errors(peak_message, extra_errors)
        if peak_message
        else "",
    )


@player_matcher.handle()
async def handle_player(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    ensure_extended_packets()
    player_id: int = state[PLAYER_ID_KEY]
    extra_errors: list[str] = []
    enabled_sections = set(plugin_config.seer_query_config.player.sections)
    show_local_rank = "local_rank" in enabled_sections
    has_collection = bool(
        {"collection", "rank", "local_rank", "achievement"} & enabled_sections
    )
    needs_peak_section = "peak" in enabled_sections
    needs_online_info = "basic" in enabled_sections
    detail_task: asyncio.Task[PlayerDetailMessages] | None = None

    try:
        game = get_game_client()
        user_info, more_info, online_info = await asyncio.wait_for(
            asyncio.gather(
                game.get_user_info(player_id),
                game.get_more_user_info(player_id),
                _optional_extra(
                    "在线状态",
                    needs_online_info,
                    lambda: game.get_user_online_info(player_id),
                    None,
                    extra_errors,
                ),
            ),
            timeout=plugin_config.seer_query_config.player.timeout_seconds,
        )
        await mark_headless_available(source="米米号查询", user_id=int(game.user_id))

        team_name = "无"
        if getattr(user_info, "team_id", 0) > 0:
            try:
                team_info = await asyncio.wait_for(
                    game.get_team_info(user_info.team_id),
                    timeout=min(
                        5.0,
                        plugin_config.seer_query_config.team.timeout_seconds,
                    ),
                )
                team_name = team_info.name
            except Exception:  # noqa: BLE001
                team_name = str(user_info.team_id)

        if has_collection or needs_peak_section or QUERY_CONFIG.local_rank.enabled:
            detail_task = _create_player_detail_task(
                player_id=player_id,
                user_info=user_info,
                more_info=more_info,
                has_collection=has_collection,
                needs_peak_section=needs_peak_section,
                show_local_rank=show_local_rank,
            )

        player_message = _format_compact_player_info(
            user_info,
            more_info,
            team_name=team_name,
            online_info=online_info,
            unity_peak=UnityPeakInfo(),
            peak_rank_summary=PeakSeasonRankSummary.empty(),
            local_summary=LocalRankSummary(),
            has_collection=has_collection,
            has_peak=needs_peak_section,
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
        has_collection=has_collection,
        has_peak=needs_peak_section,
    )
