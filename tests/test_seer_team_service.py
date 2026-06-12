from types import SimpleNamespace

from ironsbot.services.seer.team import (
    format_team_generic_error_message,
    format_team_info,
    format_team_socket_error_message,
    format_team_timeout_message,
    format_team_unavailable_message,
    team_query_in_progress_message,
    team_query_wait_message,
)

TEAM_ID = 123456


def _team_info() -> SimpleNamespace:
    return SimpleNamespace(
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

    assert "【战队扩展信息：测试战队】" in message
    assert "战队ID：123456" in message
    assert "【等级与资源】" in message
    assert "最近缴纳时间：2000年1月1日 08:00:00（946684800）" in message
    assert "【设施等级】" not in message
    assert "【文本】" not in message


def test_team_query_messages_explain_in_progress_and_wait_states() -> None:
    in_progress = team_query_in_progress_message(TEAM_ID)
    wait = team_query_wait_message(30)

    assert "正在查询战队 123456" in in_progress
    assert "服务器维护、开服波动" in in_progress
    assert "请 30 秒后再试" in wait
    assert "短时间连续查询容易排队或超时" in wait


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
