# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass, field

from ironsbot.services.seer.binary import BufferReader

LEVEL_NAMES: tuple[str, ...] = (
    "Two",
    "Tree",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "ELEVEN",
    "TWELVE",
)
MAX_DECORATE_ITEMS = 5


def _safe_read_uint32(reader: BufferReader, default: int = 0) -> int:
    return reader.read_uint32() if reader.has_remaining(4) else default


def _safe_read_uint16(reader: BufferReader, default: int = 0) -> int:
    return reader.read_uint16() if reader.has_remaining(2) else default


def _safe_read_uint8(reader: BufferReader, default: int = 0) -> int:
    return reader.read_uint8() if reader.has_remaining(1) else default


def _assign_uint32_fields(
    target: object,
    reader: BufferReader,
    field_names: tuple[str, ...],
) -> None:
    for name in field_names:
        setattr(target, name, _safe_read_uint32(reader))


@dataclass(slots=True)
class ExtendedUserInfo:
    user_id: int = 0
    nick: str = ""
    color: int = 0
    texture: int = 0
    vip: int = 0
    is_extreme_nono: bool = False
    status: int = 0
    map_type: int = 0
    map_id: int = 0
    is_can_be_teacher: bool = False
    teacher_id: int = 0
    student_id: int = 0
    graduation_count: int = 0
    vip_level: int = 0
    team_id: int = 0
    team_is_show: bool = False
    clothes_count: int = 0
    clothes: tuple[int, ...] = ()
    clothes_level: tuple[int, ...] = ()
    fight_arena_point: int = 0
    fire_buff: int = 0
    login_time: int = 0
    ollast: int = 0
    last_offline_time: int = 0
    is_friend: bool = False
    is_black: bool = False
    head_id: int = 1
    head_frame_id: int = 14
    nick_bg: int = 33
    decorate_list: tuple[int, ...] = ()

    @classmethod
    def unpack(cls, data: bytes | bytearray | memoryview) -> "ExtendedUserInfo":
        reader = BufferReader(data)
        info = cls()
        info.user_id = reader.read_uint32()
        info.nick = reader.read_string(16)
        info.color = reader.read_uint32()
        info.texture = reader.read_uint32()
        info.vip = reader.read_uint32()
        vip_flags = reader.read_uint8()
        info.is_extreme_nono = bool((vip_flags >> 1) & 1) and info.vip in (1, 3)
        info.status = reader.read_uint32()
        info.map_type = reader.read_uint32()
        info.map_id = reader.read_uint32()
        info.is_can_be_teacher = reader.read_uint32() == 1
        info.teacher_id = reader.read_uint32()
        info.student_id = reader.read_uint32()
        info.graduation_count = reader.read_uint32()
        info.vip_level = reader.read_uint32()
        info.team_id = reader.read_uint32()
        info.team_is_show = reader.read_uint32() == 1
        info.clothes_count = reader.read_uint32()

        clothes: list[int] = []
        clothes_level: list[int] = []
        for _ in range(info.clothes_count):
            clothes.append(reader.read_uint32())
            clothes_level.append(reader.read_uint32())
        info.clothes = tuple(clothes)
        info.clothes_level = tuple(clothes_level)

        info.fight_arena_point = reader.read_uint32()
        info.fire_buff = reader.read_uint8()
        info.login_time = reader.read_uint32()
        info.ollast = reader.read_uint32()
        info.last_offline_time = info.ollast
        info.is_friend = reader.read_uint8() == 1
        info.is_black = reader.read_uint8() == 1
        info.head_id = reader.read_uint32() or 1
        info.head_frame_id = reader.read_uint32() or 14
        info.nick_bg = reader.read_uint32() or 33

        decorate: list[int] = []
        while reader.has_remaining(4) and len(decorate) < MAX_DECORATE_ITEMS:
            decorate.append(reader.read_uint32())
        info.decorate_list = tuple(decorate)
        return info


@dataclass(slots=True)
class ExtendedMoreInfo:
    user_id: int = 0
    nick: str = ""
    reg_time: int = 0
    is_extreme_nono: bool = False
    pet_all_num: int = 0
    pet_max_lev: int = 0
    total_class_wins: int = 0
    total_achieve: int = 0
    achie_shine: int = 0
    achie_rank: int = 0
    cur_title: int = 0
    boss_achievement: tuple[bool, ...] = ()
    graduation_count: int = 0
    mon_king_win: int = 0
    team_boss: int = 0
    mess_win: int = 0
    lucky_fight_win: int = 0
    fight_arena_win: int = 0
    royale_win: int = 0
    dark_fight_win: int = 0
    max_fresh_stage: int = 0
    max_stage: int = 0
    max_king_stage: int = 0
    max_king_hero_stage: int = 0
    max_ladder_state: int = 0
    max_fortune_state: int = 0
    max_arena_wins: int = 0
    delta_top_honour: int = 0
    cur_top_honour: int = 0
    delta_top_lv: int = 0
    top_win_count: int = 0
    top_loss_count: int = 0
    max_top_win_succ: int = 0
    cur_top_win_succ: int = 0
    top_levels: dict[str, dict[str, int]] = field(default_factory=dict)
    high_fight_win: int = 0
    trainer_door_num: int = 0
    carnival_total_score: int = 0
    hurdles_win_num: int = 0
    hurdles_lose_num: int = 0
    tug_win_num: int = 0
    tug_lose_num: int = 0
    tug_draw_num: int = 0
    jump_num: int = 0
    max_space_arena_wins: int = 0
    extreme_law_level: int = 0
    battle_lab_info: int = 0
    zheguang_win_times: int = 0
    dream_mess_wins: int = 0
    ares_union_team: int = 0

    @classmethod
    def unpack(cls, data: bytes | bytearray | memoryview) -> "ExtendedMoreInfo":
        reader = BufferReader(data)
        info = cls()
        info.user_id = reader.read_uint32()
        info.nick = reader.read_string(16)
        info.reg_time = reader.read_uint32()
        info.is_extreme_nono = bool((reader.read_uint8() >> 1) & 1)
        _assign_uint32_fields(
            info,
            reader,
            (
                "pet_all_num",
                "pet_max_lev",
                "total_class_wins",
                "total_achieve",
                "achie_shine",
                "achie_rank",
                "cur_title",
            ),
        )

        info.boss_achievement = tuple(
            bool(_safe_read_uint8(reader)) for _ in range(199)
        )

        _assign_uint32_fields(
            info,
            reader,
            (
                "graduation_count",
                "mon_king_win",
                "team_boss",
                "mess_win",
                "lucky_fight_win",
                "fight_arena_win",
                "royale_win",
                "dark_fight_win",
                "max_fresh_stage",
                "max_stage",
                "max_king_stage",
                "max_king_hero_stage",
                "max_ladder_state",
                "max_fortune_state",
                "max_arena_wins",
                "delta_top_honour",
                "cur_top_honour",
                "delta_top_lv",
                "top_win_count",
                "top_loss_count",
                "max_top_win_succ",
                "cur_top_win_succ",
            ),
        )

        info.top_levels = {}
        for name in LEVEL_NAMES:
            info.top_levels[f"top_{name}"] = {
                "Lvl": _safe_read_uint32(reader),
                "Win": _safe_read_uint32(reader),
                "Lose": _safe_read_uint32(reader),
                "Max_Win": _safe_read_uint32(reader),
                "Sur_Win": _safe_read_uint32(reader),
            }

        info.high_fight_win = _safe_read_uint16(reader)
        if reader.has_remaining(12):
            reader.skip(12)

        _assign_uint32_fields(
            info,
            reader,
            (
                "trainer_door_num",
                "carnival_total_score",
                "hurdles_win_num",
                "hurdles_lose_num",
                "tug_win_num",
                "tug_lose_num",
                "tug_draw_num",
                "jump_num",
            ),
        )

        if reader.has_remaining(12):
            reader.skip(12)

        _assign_uint32_fields(
            info,
            reader,
            (
                "max_space_arena_wins",
                "extreme_law_level",
                "battle_lab_info",
                "zheguang_win_times",
                "dream_mess_wins",
                "ares_union_team",
            ),
        )
        return info


def ensure_extended_packets() -> None:
    from ironsbot.plugins.headless_seer.command_id import COMMAND_ID
    from ironsbot.plugins.headless_seer.core.register import packet_register

    packet_register[COMMAND_ID.GET_USER_INFO] = ExtendedUserInfo  # type: ignore[assignment]
    packet_register[COMMAND_ID.GET_MORE_USER_INFO] = ExtendedMoreInfo  # type: ignore[assignment]
