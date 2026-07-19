# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Annotated

import ironsbot.integrations.headless_seer.packet.fields as f
from ironsbot.integrations.headless_seer.packet.packet import Deserializable


class SimpleTeamInfo(Deserializable):
    team_id: f.UInt
    leader: f.UInt
    super_core_num: f.UInt
    member_count: f.UInt
    interest: f.UInt
    join_flag: f.UInt
    visit_flag: f.UInt
    score: f.UInt
    exp: f.UInt
    name: Annotated[str, f.Unicode[16]]
    slogan: Annotated[str, f.Unicode[60]]
    notice: Annotated[str, f.Unicode[60]]
    logo_bg: f.Short
    logo_icon: f.Short
    logo_color: f.Short
    txt_color: f.Short
    logo_word: Annotated[str, f.Unicode[4]]
    new_team_level: f.UInt
    tech_center_level: f.UInt
    bonus_center_level: f.UInt
    res_center_level: f.UInt
    drawing_uint: f.UInt
    total_boss_dmg: f.UInt
    team_func_disalbed: f.UInt
    last_pay_time: f.UInt
