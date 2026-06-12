from types import SimpleNamespace

from ironsbot.services.seer.team import format_team_info


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
