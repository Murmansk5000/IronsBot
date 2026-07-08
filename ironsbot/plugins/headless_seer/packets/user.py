# SPDX-License-Identifier: GPL-3.0-or-later
# public static void setForSimpleInfo(UserInfo info, ByteArray data)
# {
# 	info.hasSimpleInfo = true;
# 	data.position = 0;
# 	info.userID = (int)data.ReadUnsignedInt();
# 	info.nick = data.ReadUTFByte(16);
# 	info.color = (int)data.ReadUnsignedInt();
# 	info.texture = (int)data.ReadUnsignedInt();
# 	info.vip = (int)data.ReadUnsignedInt();
# 	int num = (int)data.ReadUnsignedByte();
# 	info.isExtremeNono = BitUtil.getBit(num, 1) > 0;
# 	if (!info.isVip)
# 	{
# 		info.isExtremeNono = false;
# 	}
# 	info.status = (int)data.ReadUnsignedInt();
# 	info.mapType = (int)data.ReadUnsignedInt();
# 	info.mapID = (int)data.ReadUnsignedInt();
# 	info.isCanBeTeacher = data.ReadUnsignedInt() == 1U;
# 	info.teacherID = (int)data.ReadUnsignedInt();
# 	info.studentID = (int)data.ReadUnsignedInt();
# 	info.graduationCount = (int)data.ReadUnsignedInt();
# 	info.vipLevel = (int)data.ReadUnsignedInt();
# 	TeamInfo teamInfo = new TeamInfo(null);
# 	teamInfo.id = (int)data.ReadUnsignedInt();
# 	teamInfo.isShow = data.ReadUnsignedInt() > 0U;
# 	info.teamInfo = teamInfo;
# 	info.teamID = teamInfo.id;
# 	int num2 = (int)data.ReadUnsignedInt();
# 	info.clothes.Clear();
# 	for (int i = 0; i < num2; i++)
# 	{
# 		int num3 = (int)data.ReadUnsignedInt();
# 		int num4 = (int)data.ReadUnsignedInt();
# 		info.clothes.Add(new PeopleItemInfo(num3, num4));
# 	}
# 	info.fightArenaPoint = (int)data.ReadUnsignedInt();
# 	info.fireBuff = (int)data.ReadUnsignedByte();
# 	info.loginTime = (int)data.ReadUnsignedInt();
# 	info.ollast = (int)data.ReadUnsignedInt();
# 	info.isFriend = data.ReadUnsignedByte() > 0;
# 	info.isBlack = data.ReadUnsignedByte() > 0;
# 	info._head_id = (int)data.ReadUnsignedInt();
# 	info._head_id = ((info._head_id == 0) ? 1 : info._head_id);
# 	info._head_frame_id = (int)data.ReadUnsignedInt();
# 	info.nickBg = (int)data.ReadUnsignedInt();
# 	info.nickBg = ((info.nickBg == 0) ? 33 : info.nickBg);
# }
from typing import Annotated

import ironsbot.integrations.headless_seer.packet.fields as f
from ironsbot.integrations.headless_seer.packet.packet import Deserializable


class UserInfo(Deserializable):
    user_id: f.UInt
    nick: Annotated[str, f.Unicode[16]]
    color: f.UInt
    texture: f.UInt
    vip: f.UInt
    is_extreme_nono: Annotated[bool, f.Byte]
    status: f.UInt
    map_type: f.UInt
    map_id: f.UInt
    is_can_be_teacher: Annotated[bool, f.UInt]
    teacher_id: f.UInt
    student_id: f.UInt
    graduation_count: f.UInt
    vip_level: f.UInt
    team_id: f.UInt
    team_is_show: f.UInt
    clothes_count: f.UInt
    clothes: Annotated[tuple[int, ...], f.Array[f.size_by("clothes_count"), f.UInt]]
    clothes_level: Annotated[
        tuple[int, ...], f.Array[f.size_by("clothes_count"), f.UInt]
    ]
    fight_arena_point: f.UInt
    fire_buff: f.Byte
    login_time: f.UInt
    ollast: f.UInt
    is_friend: Annotated[bool, f.Byte]
    is_black: Annotated[bool, f.Byte]
    head_id: f.UInt
    head_frame_id: f.UInt
    nick_bg: f.UInt

    def __post_init__(self) -> None:
        self.head_id = self.head_id or 1
        self.nick_bg = self.nick_bg or 33
        self.is_extreme_nono = self.is_extreme_nono > 0
        self.is_can_be_teacher = self.is_can_be_teacher > 0
        self.is_friend = self.is_friend > 0
        self.is_black = self.is_black > 0
        cloth = []
        level = []
        for i in range(self.clothes_count):
            cloth.append(self.clothes[i] or 0)
            level.append(self.clothes_level[i] or 0)
        self.clothes = tuple(cloth)
        self.clothes_level = tuple(level)


class MoreInfo(Deserializable):
    user_id: f.UInt
    nick: Annotated[str, f.Unicode[16]]
    reg_time: f.UInt
    is_extreme_nono: f.Byte
    pet_all_num: f.UInt
    pet_max_lev: f.UInt
    total_class_wins: f.UInt
    total_achieve: f.UInt
    achie_shine: f.UInt
    achie_rank: f.UInt
    cur_title: f.UInt


class UserForeverValue(Deserializable):
    value: f.Int


class OnLineInfo(Deserializable):
    user_id: f.UInt
    server_id: f.UInt
    map_type: f.UInt
    map_id: f.UInt


class OnLineInfos(Deserializable):
    length: f.UInt
    infos: Annotated[list[OnLineInfo], f.Array[f.size_by("length"), OnLineInfo]]
