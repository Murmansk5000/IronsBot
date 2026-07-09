# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.formatting import yes_no
from ironsbot.services.seer.player_formatting_common import (
    filter_blank_lines,
    format_id_name,
    format_id_name_list,
    format_status,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPartTwoInfo


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


__all__ = ["format_hidden_player_details"]
