from dataclasses import dataclass

from ironsbot.services.seer.team import (
    format_team_generic_error_message,
    format_team_info,
    format_team_socket_error_message,
    format_team_timeout_message,
    format_team_unavailable_message,
)

TEAM_ID = 123456


@dataclass(frozen=True)
class TeamInfo:
    name: str
    team_id: int
    leader: int
    member_count: int
    new_team_level: int
    exp: int
    score: int
    super_core_num: int
    last_pay_time: int
    tech_center_level: int
    bonus_center_level: int
    res_center_level: int
    total_boss_dmg: int
    interest: int
    join_flag: int
    visit_flag: int
    team_func_disalbed: int
    drawing_uint: int
    logo_bg: int
    logo_icon: int
    logo_color: int
    txt_color: int
    logo_word: str
    slogan: str
    notice: str


def _team_info() -> TeamInfo:
    return TeamInfo(
        name="测试战队",
        team_id=123456,
        leader=654321,
        member_count=42,
        new_team_level=9,
        exp=8888,
        score=777,
        super_core_num=6,
        last_pay_time=946684800,
        tech_center_level=3,
        bonus_center_level=4,
        res_center_level=5,
        total_boss_dmg=9999,
        interest=1,
        join_flag=2,
        visit_flag=3,
        team_func_disalbed=0,
        drawing_uint=123,
        logo_bg=11,
        logo_icon=22,
        logo_color=33,
        txt_color=44,
        logo_word="T",
        slogan="一起冲",
        notice="今晚集合",
    )


def test_format_team_info_respects_enabled_sections() -> None:
    message = format_team_info(_team_info(), {"basic", "resource"})

    assert "【战队信息：测试战队】" in message
    assert "战队ID：123456" in message
    assert "战队等级：9" in message
    assert "战队资源：777" in message
    assert "最近缴纳时间" not in message
    assert "【设施等级】" not in message
    assert "【文本】" not in message


def test_team_error_messages_include_team_id_and_reason() -> None:
    assert "战队 123456 暂时查不了" in format_team_unavailable_message(TEAM_ID)
    assert (
        format_team_timeout_message(TEAM_ID)
        == "❌ 战队 123456 查询超时，请稍后再试。"
    )
    assert (
        format_team_socket_error_message(TEAM_ID, "连接断开")
        == "❌ 战队 123456 连接断开"
    )
    assert (
        format_team_generic_error_message(TEAM_ID, "boom")
        == "❌ 战队 123456 查询失败：boom"
    )
