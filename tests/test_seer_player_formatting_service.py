from types import SimpleNamespace

from ironsbot.services.seer.player_formatting import (
    append_extra_errors,
    format_compact_player_info,
    format_id_name,
    format_id_name_list,
    format_online_text,
    format_player_detail_messages,
    format_player_identity,
    format_team_text,
    format_vip,
    format_win_rate,
)

PLAYER_ID = 105023264
TEAM_ID = 686376929
REG_TIME = 946684800


class _LocalSummary:
    def __init__(self, rank_text: str = "") -> None:
        self._rank_text = rank_text

    def sample_rank(self, _key: str) -> str:
        return self._rank_text


def _rank_result(score: int, rank: int = 1) -> SimpleNamespace:
    return SimpleNamespace(score=score, rank=rank)


def _rank_summary() -> SimpleNamespace:
    return SimpleNamespace(
        book=_rank_result(1234),
        achieve=_rank_result(56),
        breakdown=SimpleNamespace(
            pet_kind=_rank_result(100),
            skin=_rank_result(10),
            outfit_suit=_rank_result(20),
            outfit_part=_rank_result(30),
            mount=_rank_result(5),
            countermark=_rank_result(8),
            unlocked_count=173,
        ),
    )


def _peak_summary() -> SimpleNamespace:
    return SimpleNamespace(
        standard=SimpleNamespace(rank=1),
        wild=SimpleNamespace(rank=None),
        expert=SimpleNamespace(rank=3),
    )


def _unity_peak() -> SimpleNamespace:
    return SimpleNamespace(
        current_j_rank=3,
        current_j_star=2,
        history_j_rank=4,
        history_j_star=1,
        current_j_win=6,
        current_j_all=10,
        current_k_rank=2,
        current_k_star=5,
        history_k_rank=3,
        history_k_star=4,
        current_k_win=0,
        current_k_all=0,
        current_z_score=1234,
        history_z_score=2345,
        current_z_win=2,
        current_z_all=4,
    )


def test_format_id_name_helpers_render_missing_ids_and_known_names() -> None:
    names = {1: "称号A", 2: "称号B"}

    assert format_id_name(0, names) == "无"
    assert format_id_name(1, names) == "称号A（1）"
    assert format_id_name(9, names) == "9"
    assert format_id_name_list((0, 1, 2), names) == "称号A（1）、称号B（2）"


def test_format_player_identity_team_vip_and_online_text() -> None:
    user_info = SimpleNamespace(team_id=TEAM_ID, team_is_show=False, vip=1, vip_level=6)
    online_info = SimpleNamespace(server_id=1, map_type=2, map_id=3)

    assert (
        format_player_identity(PLAYER_ID, "赛小息")
        == "米米号：105023264（赛小息）"
    )
    assert (
        format_team_text(user_info, "测试战队")
        == "测试战队（战队ID：686376929，隐藏）"
    )
    assert format_vip(user_info) == "是（等级：6）"
    assert (
        format_online_text(online_info)
        == "在线（服务器：1，地图类型：2，地图ID：3）"
    )
    assert format_online_text(None) == "离线"


def test_format_win_rate_handles_empty_and_non_empty_records() -> None:
    assert format_win_rate(0, 0) == "当前赛季未参赛"
    assert format_win_rate(2, 3) == "2/3=66.667%"


def test_format_compact_player_info_keeps_basic_sections_and_prompts() -> None:
    user_info = SimpleNamespace(
        user_id=PLAYER_ID,
        nick="赛小息",
        vip=0,
        login_time=0,
        last_offline_time=0,
        team_id=0,
    )
    more_info = SimpleNamespace(reg_time=REG_TIME)

    message = format_compact_player_info(
        user_info,
        more_info,
        team_name="无",
        online_info=None,
        unity_peak=SimpleNamespace(),
        peak_rank_summary=SimpleNamespace(),
        local_summary=_LocalSummary(),
        has_collection=True,
        has_peak=True,
        show_peak=False,
        extra_errors=["在线状态失败"],
    )

    assert "🤖【玩家信息】" in message
    assert "米米号：105023264（赛小息）" in message
    assert "注册时间：2000年1月1日 08:00:00" in message
    assert "战队：未加入" in message
    assert "回复“收集”查看收集与排行" in message
    assert "回复“巅峰”查看巅峰之战" in message
    assert "在线状态失败" in message


def test_format_player_detail_messages_builds_collection_and_peak() -> None:
    user_info = SimpleNamespace(nick="赛小息")
    more_info = SimpleNamespace(pet_all_num=321, total_achieve=56)
    unity_part_one = SimpleNamespace(achievement_num=7, pet_kind_num=100, skin_num=10)

    messages = format_player_detail_messages(
        player_id=PLAYER_ID,
        user_info=user_info,
        more_info=more_info,
        unity_part_one=unity_part_one,
        unity_peak=_unity_peak(),
        rank_summary=_rank_summary(),
        peak_rank_summary=_peak_summary(),
        local_rank_summary=_LocalSummary("样本第1"),
        empty_local_rank_summary=_LocalSummary(),
        has_collection=True,
        needs_peak_section=True,
        show_local_rank=True,
        extra_errors=["全服排行失败"],
    )

    assert "📚【收集与排行】" in messages.collection_message
    assert "米米号：105023264（赛小息）" in messages.collection_message
    assert "图鉴积分：1234" in messages.collection_message
    assert "样本第1" in messages.collection_message
    assert "【巅峰之战】" in messages.peak_message
    assert "竞技：" in messages.peak_message
    assert "样本段位第1" in messages.peak_message
    assert "全服排行失败" in messages.collection_message
    assert "全服排行失败" in messages.peak_message


def test_format_player_detail_messages_can_hide_local_rank_details() -> None:
    user_info = SimpleNamespace(nick="赛小息")
    more_info = SimpleNamespace(pet_all_num=321, total_achieve=56)
    unity_part_one = SimpleNamespace(achievement_num=7, pet_kind_num=100, skin_num=10)

    messages = format_player_detail_messages(
        player_id=PLAYER_ID,
        user_info=user_info,
        more_info=more_info,
        unity_part_one=unity_part_one,
        unity_peak=_unity_peak(),
        rank_summary=_rank_summary(),
        peak_rank_summary=_peak_summary(),
        local_rank_summary=_LocalSummary("样本第1"),
        empty_local_rank_summary=_LocalSummary(),
        has_collection=True,
        needs_peak_section=False,
        show_local_rank=False,
        extra_errors=[],
    )

    assert "样本第1" not in messages.collection_message
    assert messages.peak_message == ""


def test_append_extra_errors_preserves_existing_message_when_empty() -> None:
    assert append_extra_errors("正文", []) == "正文"
    assert append_extra_errors("正文", ["A", "B"]) == "正文\n\n【扩展数据提示】\n\nA；B"
