# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Callable
from typing import Any

from nonebot import logger
from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.utils.matcher import enter_prompt_loop, prompt_session_manager
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..config import plugin_config
from ..group import matcher_group
from ..packets import ensure_extended_packets
from ._args import has_numeric_arg, parse_numeric_id
from ._client import get_game_client
from ._format import format_datetime, yes_no
from ._local_rank import LocalRankSummary, update_local_rank_cache
from ._rank import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
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
    fetch_unity_part_two,
    fetch_unity_peak,
)

PLAYER_ID_KEY = "player_id"
PLAYER_COLLECTION_KEY = "_player_collection_message"
METRIC_SEPARATOR = "\uFF5C"

player_matcher = matcher_group.on_message(
    rule=(
        startswith_or_endswith(prefixes=("查询玩家信息", "米米号"), suffixes=())
        & has_numeric_arg
        & no_reply()
    ),
)

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


def _global_rank_text(rank: int | None) -> str:
    return f"全服第{rank}" if rank is not None else ""


def _sample_rank_text(summary: LocalRankSummary, key: str) -> str:
    return summary.sample_rank(key)


def _format_metric_line(
    title: str,
    value: int | None,
    *,
    global_rank: int | None = None,
    local_summary: LocalRankSummary,
    local_key: str,
) -> str | None:
    if value is None or value <= 0:
        return None

    metric_text = _join_metric_parts(
        str(value),
        _global_rank_text(global_rank),
        _sample_rank_text(local_summary, local_key),
    )
    return f"{title}：{metric_text}"


def _format_peak_rank_text(rank: int | None) -> str:
    return f"赛季榜第{rank}" if rank is not None else "赛季榜未上榜"


def _format_local_rank_suffix(summary: LocalRankSummary, key: str) -> str:
    text = summary.sample_rank(key)
    return f"（{text}）" if text else ""


def _format_peak_line(  # noqa: PLR0913
    title: str,
    *,
    current: str,
    history: str,
    win_rate: str,
    rank: int | None,
    local_summary: LocalRankSummary,
    score_key: str,
    win_rate_key: str,
) -> str:
    win_rate_text = (
        f"胜率{win_rate}{_format_local_rank_suffix(local_summary, win_rate_key)}"
    )
    rank_text = (
        f"{_format_peak_rank_text(rank)}"
        f"{_format_local_rank_suffix(local_summary, score_key)}"
    )
    return (
        f"{title}：{current}{METRIC_SEPARATOR}历史{history}"
        f"{METRIC_SEPARATOR}{win_rate_text}{METRIC_SEPARATOR}{rank_text}"
    )


def _format_compact_peak_section(
    peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
) -> str:
    return "\n".join(
        [
            "【巅峰之战】",
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
                win_rate=_format_win_rate(
                    peak.current_j_win,
                    peak.current_j_all,
                ),
                rank=peak_rank_summary.standard.rank,
                local_summary=local_summary,
                score_key="peak_standard",
                win_rate_key="peak_standard_win_rate",
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
                win_rate=_format_win_rate(
                    peak.current_k_win,
                    peak.current_k_all,
                ),
                rank=peak_rank_summary.wild.rank,
                local_summary=local_summary,
                score_key="peak_wild",
                win_rate_key="peak_wild_win_rate",
            ),
            _format_peak_line(
                "专家",
                current=f"{peak.current_z_score}分",
                history=f"{peak.history_z_score}分",
                win_rate=_format_win_rate(
                    peak.current_z_win,
                    peak.current_z_all,
                ),
                rank=peak_rank_summary.expert.rank,
                local_summary=local_summary,
                score_key="peak_expert",
                win_rate_key="peak_expert_win_rate",
            ),
        ]
    )


def _format_collection_info(
    more_info: Any,
    *,
    unity_part_one: UnityPartOneInfo,
    rank_summary: PlayerRankSummary,
    local_summary: LocalRankSummary,
) -> str:
    breakdown = rank_summary.breakdown
    outfit_suit_score = (
        None if breakdown.outfit_suit is None else breakdown.outfit_suit.score
    )
    outfit_suit_rank = (
        None if breakdown.outfit_suit is None else breakdown.outfit_suit.rank
    )
    outfit_part_score = (
        None if breakdown.outfit_part is None else breakdown.outfit_part.score
    )
    outfit_part_rank = (
        None if breakdown.outfit_part is None else breakdown.outfit_part.rank
    )
    countermark_score = (
        None if breakdown.countermark is None else breakdown.countermark.score
    )
    countermark_rank = (
        None if breakdown.countermark is None else breakdown.countermark.rank
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
            global_rank=rank_summary.book.rank,
            local_summary=local_summary,
            local_key="book_score",
        ),
        _format_metric_line(
            "成就点数",
            getattr(more_info, "total_achieve", 0),
            global_rank=rank_summary.achieve.rank,
            local_summary=local_summary,
            local_key="achievement_score",
        ),
        _format_metric_line(
            "精灵图鉴",
            unity_part_one.pet_kind_num,
            global_rank=None if breakdown.pet_kind is None else breakdown.pet_kind.rank,
            local_summary=local_summary,
            local_key="pet_kind_count",
        ),
        _format_metric_line(
            "皮肤图鉴",
            unity_part_one.skin_num,
            global_rank=None if breakdown.skin is None else breakdown.skin.rank,
            local_summary=local_summary,
            local_key="skin_count",
        ),
        _format_metric_line(
            "套装图鉴",
            outfit_suit_score,
            global_rank=outfit_suit_rank,
            local_summary=local_summary,
            local_key="outfit_suit_count",
        ),
        _format_metric_line(
            "部件图鉴",
            outfit_part_score,
            global_rank=outfit_part_rank,
            local_summary=local_summary,
            local_key="outfit_part_count",
        ),
        _format_metric_line(
            "座驾图鉴",
            None if breakdown.mount is None else breakdown.mount.score,
            global_rank=None if breakdown.mount is None else breakdown.mount.rank,
            local_summary=local_summary,
            local_key="mount_count",
        ),
        _format_metric_line(
            "刻印图鉴",
            countermark_score,
            global_rank=countermark_rank,
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
    lines = ["📚【收集与排行】"]
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
    state: T_State,
) -> None:
    state[PLAYER_ID_KEY] = await parse_numeric_id(
        matcher,
        state,
        min_value=50000,
        max_value=2_000_000_000,
        error_message="❌ 米米号无效，请输入 50000 ~ 2000000000 之间的数字",
    )


async def _handle_collection_reply(matcher: Matcher, state: T_State) -> None:
    message = state.get(PLAYER_COLLECTION_KEY)
    if not message:
        raise FinishedException

    await matcher.finish(message)


async def _send_player_info_with_collection_prompt(
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    player_message: str,
    collection_message: str,
) -> None:
    state[PLAYER_COLLECTION_KEY] = collection_message

    session_id = event.get_session_id()
    version = prompt_session_manager.acquire(session_id)

    def _is_collection_request(next_event: Event) -> bool:
        return (
            next_event.get_session_id() == session_id
            and next_event.get_plaintext().strip() == "收集"
        )

    rule = prompt_session_manager.make_rule(
        session_id,
        version,
        _is_collection_request,
    )
    await enter_prompt_loop(
        matcher,
        handlers=[_handle_collection_reply],
        rule=rule,
        prompt=player_message,
    )


@player_matcher.handle()
async def handle_player(matcher: Matcher, event: Event, state: T_State) -> None:
    ensure_extended_packets()
    player_id: int = state[PLAYER_ID_KEY]
    game = get_game_client()
    extra_errors: list[str] = []
    enabled_sections = set(plugin_config.seer_query_player_sections)
    show_local_rank = "local_rank" in enabled_sections
    has_collection = bool(
        {"collection", "rank", "local_rank", "achievement"} & enabled_sections
    )

    try:
        user_info, more_info = await asyncio.gather(
            game.get_user_info(player_id),
            game.get_more_user_info(player_id),
        )

        team_name = "无"
        if getattr(user_info, "team_id", 0) > 0:
            try:
                team_info = await game.get_team_info(user_info.team_id)
                team_name = team_info.name
            except Exception:  # noqa: BLE001
                team_name = str(user_info.team_id)

        needs_unity_part_one = has_collection
        needs_unity_part_two = False
        needs_peak_section = "peak" in enabled_sections
        needs_unity_peak = needs_peak_section
        needs_local_rank = plugin_config.seer_query_local_rank
        needs_online_info = "basic" in enabled_sections
        needs_rank_summary = has_collection or needs_local_rank

        if needs_local_rank:
            needs_unity_part_one = True
            needs_unity_peak = True

        (
            unity_part_one,
            _unity_part_two,
            unity_peak,
            online_info,
        ) = await asyncio.gather(
            _optional_extra(
                "展示/收集数据",
                needs_unity_part_one,
                lambda: fetch_unity_part_one(game, player_id),
                UnityPartOneInfo(),
                extra_errors,
            ),
            _optional_extra(
                "展示精灵数据",
                needs_unity_part_two,
                lambda: fetch_unity_part_two(game, player_id),
                UnityPartTwoInfo(),
                extra_errors,
            ),
            _optional_extra(
                "巅峰数据",
                needs_unity_peak,
                lambda: fetch_unity_peak(game, player_id),
                UnityPeakInfo(),
                extra_errors,
            ),
            _optional_extra(
                "在线状态",
                needs_online_info,
                lambda: game.get_user_online_info(player_id),
                None,
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

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        await matcher.finish(f"❌ 米米号 {player_id} 查询失败：{e}")

    collection_message = (
        _format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=visible_local_rank_summary,
        )
        if has_collection
        else ""
    )
    player_message = _format_compact_player_info(
        user_info,
        more_info,
        team_name=team_name,
        online_info=online_info,
        unity_peak=unity_peak,
        peak_rank_summary=peak_rank_summary,
        local_summary=visible_local_rank_summary,
        has_collection=bool(collection_message),
        show_peak=needs_peak_section,
        extra_errors=extra_errors,
    )

    if collection_message:
        await _send_player_info_with_collection_prompt(
            matcher,
            event,
            state,
            player_message=player_message,
            collection_message=collection_message,
        )

    await matcher.finish(player_message)
