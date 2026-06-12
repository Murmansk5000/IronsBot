# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.formatting import format_datetime, yes_no

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank import LocalRankSummary
    from ironsbot.services.seer.rank import (
        PeakSeasonRankSummary,
        PlayerRankSummary,
        RankLookupResult,
    )
    from ironsbot.services.seer.sequ_extra import (
        UnityPartOneInfo,
        UnityPartTwoInfo,
        UnityPeakInfo,
    )

METRIC_SEPARATOR = "\uFF5C"
PEAK_RANK_NAMES = {
    0: "学徒",
    1: "猛将",
    2: "天骄",
    3: "王者",
    4: "圣皇",
    5: "宇宙圣皇",
}


def filter_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if line == "" and (not result or result[-1] == ""):
            continue
        result.append(line)

    while result and result[-1] == "":
        result.pop()

    return result


def format_id_name(item_id: int, names: dict[int, str]) -> str:
    if item_id <= 0:
        return "无"

    name = names.get(item_id)
    if not name:
        return str(item_id)

    return f"{name}（{item_id}）"


def format_id_name_list(ids: tuple[int, ...], names: dict[int, str]) -> str:
    items = [format_id_name(item_id, names) for item_id in ids if item_id > 0]
    return "、".join(items) if items else "无"


def format_team_text(user_info: Any, team_name: str) -> str:
    team_id = getattr(user_info, "team_id", 0)
    if team_id <= 0:
        return "未加入"

    show_text = "展示" if getattr(user_info, "team_is_show", False) else "隐藏"
    return f"{team_name}（战队ID：{team_id}，{show_text}）"


def format_player_identity(
    player_id: int,
    nick: str | None = None,
) -> str:
    if nick:
        return f"米米号：{player_id}（{nick}）"
    return f"米米号：{player_id}"


def format_online_text(online_info: Any | None) -> str:
    if online_info is None:
        return "离线"

    return (
        "在线"
        f"（服务器：{online_info.server_id}，"
        f"地图类型：{online_info.map_type}，地图ID：{online_info.map_id}）"
    )


def format_status(value: int) -> str:
    if value == 1:
        return "正常"
    if value == 0:
        return "未知"
    return f"状态值：{value}"


def format_vip(user_info: Any) -> str:
    if getattr(user_info, "vip", 0):
        return f"是（等级：{getattr(user_info, 'vip_level', 0)}）"
    return "否"


def format_rank_star_compact(rank: int, star: int) -> str:
    name = PEAK_RANK_NAMES.get(rank, f"段位{rank}")
    return f"{name}{star}星"


def format_win_rate(wins: int, total: int) -> str:
    if total <= 0:
        return "当前赛季未参赛"

    return f"{wins}/{total}={wins / total * 100:.3f}%"


def join_metric_parts(*parts: str) -> str:
    return METRIC_SEPARATOR.join(part for part in parts if part)


def rank_lookup_text(result: RankLookupResult | None) -> str:
    if result is None:
        return ""
    if result.rank is not None:
        return f"全服第{result.rank}"
    if result.queried and result.searched_limit > 0:
        return f"全服未进入前{result.searched_limit}"
    return ""


def sample_rank_text(summary: LocalRankSummary, key: str) -> str:
    return summary.sample_rank(key)


def format_metric_line(
    title: str,
    value: int | None,
    *,
    rank_result: RankLookupResult | None = None,
    local_summary: LocalRankSummary,
    local_key: str,
) -> str | None:
    value_text = str(value) if value is not None and value >= 0 else "暂无数据"

    metric_text = join_metric_parts(
        value_text,
        rank_lookup_text(rank_result),
        sample_rank_text(local_summary, local_key),
    )
    return f"{title}：{metric_text}"


def format_peak_rank_text(rank: int | None) -> str:
    return f"赛季榜第{rank}" if rank is not None else "赛季榜未上榜"


def format_local_rank_suffix(
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


def format_peak_line(  # noqa: PLR0913
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
            f"{format_local_rank_suffix(local_summary, match_key, label='样本场次')}"
        )
    win_rate_text = (
        f"胜率{win_rate}"
        f"{format_local_rank_suffix(local_summary, win_rate_key, label='样本胜率')}"
    )
    rank_text = (
        f"{format_peak_rank_text(rank)}"
        f"{format_local_rank_suffix(local_summary, score_key, label='样本段位')}"
    )
    return (
        f"{title}：{current}{METRIC_SEPARATOR}历史{history}"
        f"{METRIC_SEPARATOR}"
        f"{join_metric_parts(match_text, win_rate_text, rank_text)}"
    )


def format_compact_peak_section(
    peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    *,
    player_id: int | None = None,
    nick: str | None = None,
) -> str:
    lines = ["【巅峰之战】"]
    if player_id is not None:
        lines.append(format_player_identity(player_id, nick))

    lines.extend(
        [
            format_peak_line(
                "竞技",
                current=format_rank_star_compact(
                    peak.current_j_rank,
                    peak.current_j_star,
                ),
                history=format_rank_star_compact(
                    peak.history_j_rank,
                    peak.history_j_star,
                ),
                match_count=peak.current_j_all,
                win_rate=format_win_rate(
                    peak.current_j_win,
                    peak.current_j_all,
                ),
                rank=peak_rank_summary.standard.rank,
                local_summary=local_summary,
                score_key="peak_standard",
                win_rate_key="peak_standard_win_rate",
                match_key="peak_standard_matches",
            ),
            format_peak_line(
                "狂野",
                current=format_rank_star_compact(
                    peak.current_k_rank,
                    peak.current_k_star,
                ),
                history=format_rank_star_compact(
                    peak.history_k_rank,
                    peak.history_k_star,
                ),
                match_count=peak.current_k_all,
                win_rate=format_win_rate(
                    peak.current_k_win,
                    peak.current_k_all,
                ),
                rank=peak_rank_summary.wild.rank,
                local_summary=local_summary,
                score_key="peak_wild",
                win_rate_key="peak_wild_win_rate",
                match_key="peak_wild_matches",
            ),
            format_peak_line(
                "专家",
                current=f"{peak.current_z_score}分",
                history=f"{peak.history_z_score}分",
                match_count=peak.current_z_all,
                win_rate=format_win_rate(
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
    return "\n".join(lines)


def format_collection_info(
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
        format_metric_line(
            "精灵数量",
            getattr(more_info, "pet_all_num", 0),
            local_summary=local_summary,
            local_key="pet_total_count",
        ),
        format_metric_line(
            "图鉴积分",
            rank_summary.book.score,
            rank_result=rank_summary.book,
            local_summary=local_summary,
            local_key="book_score",
        ),
        format_metric_line(
            "成就点数",
            getattr(more_info, "total_achieve", 0),
            rank_result=rank_summary.achieve,
            local_summary=local_summary,
            local_key="achievement_score",
        ),
        format_metric_line(
            "精灵图鉴",
            unity_part_one.pet_kind_num,
            rank_result=breakdown.pet_kind,
            local_summary=local_summary,
            local_key="pet_kind_count",
        ),
        format_metric_line(
            "皮肤图鉴",
            unity_part_one.skin_num,
            rank_result=breakdown.skin,
            local_summary=local_summary,
            local_key="skin_count",
        ),
        format_metric_line(
            "套装图鉴",
            outfit_suit_score,
            rank_result=breakdown.outfit_suit,
            local_summary=local_summary,
            local_key="outfit_suit_count",
        ),
        format_metric_line(
            "部件图鉴",
            outfit_part_score,
            rank_result=breakdown.outfit_part,
            local_summary=local_summary,
            local_key="outfit_part_count",
        ),
        format_metric_line(
            "座驾图鉴",
            None if breakdown.mount is None else breakdown.mount.score,
            rank_result=breakdown.mount,
            local_summary=local_summary,
            local_key="mount_count",
        ),
        format_metric_line(
            "刻印图鉴",
            countermark_score,
            rank_result=breakdown.countermark,
            local_summary=local_summary,
            local_key="countermark_count",
        ),
        format_metric_line(
            "已解锁图鉴条目",
            breakdown.unlocked_count,
            local_summary=local_summary,
            local_key="unlocked_book_entries",
        ),
        format_metric_line(
            "成就数量",
            unity_part_one.achievement_num,
            local_summary=local_summary,
            local_key="achievement_count",
        ),
    ]
    lines = ["📚【收集与排行】", player_identity]
    lines.extend(line for line in metric_lines if line)
    return "\n".join(lines)


def format_compact_player_info(  # noqa: PLR0913
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
        f"VIP状态：{format_vip(user_info)}",
        f"注册时间：{format_datetime(getattr(more_info, 'reg_time', 0))}",
        f"最后登录：{format_datetime(getattr(user_info, 'login_time', 0))}",
        f"最后离线：{format_datetime(getattr(user_info, 'last_offline_time', 0))}",
        f"是否在线：{format_online_text(online_info)}",
        "",
        f"战队：{format_team_text(user_info, team_name)}",
    ]

    if show_peak:
        lines.extend(
            (
                "",
                format_compact_peak_section(
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

    return "\n".join(filter_blank_lines(lines))


def format_hidden_player_details(  # noqa: PLR0913
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
        f"账号状态：{format_status(getattr(user_info, 'status', 0))}",
        f"当前称号：{format_id_name(getattr(more_info, 'cur_title', 0), title_names)}",
        f"头像ID：{getattr(user_info, 'head_id', 0)}",
        f"头像框ID：{getattr(user_info, 'head_frame_id', 0)}",
        f"昵称背景ID：{getattr(user_info, 'nick_bg', 0)}",
        f"装备：{format_id_name_list(clothes, equip_names)}",
        f"幻化/装饰：{format_id_name_list(decorate, equip_names)}",
        f"可成为教官：{yes_no(getattr(user_info, 'is_can_be_teacher', False))}",
        f"老师米米号：{getattr(user_info, 'teacher_id', 0) or '无'}",
        f"学生米米号：{getattr(user_info, 'student_id', 0) or '无'}",
        f"毕业学员数：{getattr(more_info, 'graduation_count', 0)}",
        f"机器人好友：{yes_no(getattr(user_info, 'is_friend', False))}",
        f"机器人黑名单：{yes_no(getattr(user_info, 'is_black', False))}",
        f"最高精灵等级：{getattr(more_info, 'pet_max_lev', 0)}",
        f"成就闪耀值：{getattr(more_info, 'achie_shine', 0)}",
        f"Boss成就：{boss_count}/{len(boss_flags) or 199}",
        f"称号1：{format_id_name(unity_part_one.title1, title_names)}",
        f"称号2：{format_id_name(unity_part_one.title2, title_names)}",
        f"称号3：{format_id_name(unity_part_one.title3, title_names)}",
        f"称号4：{format_id_name(unity_part_one.title4, title_names)}",
        f"精灵1：{format_id_name(unity_part_two.show_pet1, pet_names)}",
        f"精灵2：{format_id_name(unity_part_two.show_pet2, pet_names)}",
        f"精灵3：{format_id_name(unity_part_two.show_pet3, pet_names)}",
        f"精灵4：{format_id_name(unity_part_two.show_pet4, pet_names)}",
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
    return "\n".join(filter_blank_lines(lines))


def append_extra_errors(message: str, extra_errors: list[str]) -> str:
    if not extra_errors:
        return message

    return "\n\n".join((message, "【扩展数据提示】", "；".join(extra_errors)))
