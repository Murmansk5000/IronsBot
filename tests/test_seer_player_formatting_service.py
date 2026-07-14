from dataclasses import dataclass
from typing import Any, cast

from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_detail_formatting import (
    append_extra_errors,
    format_player_detail_messages,
)
from ironsbot.services.seer.player_formatting_common import (
    format_login_timeline_lines,
    format_online_text,
    format_player_identity,
    format_team_text,
    format_vip,
    format_win_rate,
)

PLAYER_ID = 105023264
TEAM_ID = 987654321
REG_TIME = 946684800


def _as_any(value: object) -> Any:
    return cast("Any", value)


@dataclass(frozen=True)
class UserInfo:
    user_id: int = PLAYER_ID
    nick: str = "赛小息"
    vip: int = 0
    vip_level: int = 0
    login_time: int = 0
    last_offline_time: int = 0
    team_id: int = 0
    team_is_show: bool = True


@dataclass(frozen=True)
class OnlineInfo:
    server_id: int
    map_type: int
    map_id: int


@dataclass(frozen=True)
class MoreInfo:
    reg_time: int = REG_TIME
    pet_all_num: int = 0
    total_achieve: int = 0


@dataclass(frozen=True)
class UnityPartOne:
    achievement_num: int
    pet_kind_num: int
    skin_num: int


@dataclass(frozen=True)
class RankResult:
    score: int
    rank: int = 1


@dataclass(frozen=True)
class RankBreakdown:
    pet_kind: RankResult
    skin: RankResult
    outfit_suit: RankResult
    outfit_part: RankResult
    mount: RankResult
    countermark: RankResult
    unlocked_count: int


@dataclass(frozen=True)
class RankSummary:
    book: RankResult
    achieve: RankResult
    breakdown: RankBreakdown


@dataclass(frozen=True)
class PeakRank:
    rank: int | None


@dataclass(frozen=True)
class PeakSummary:
    standard: PeakRank
    wild: PeakRank
    expert: PeakRank


@dataclass(frozen=True)
class AutocardRankSummary:
    rank: int | None = 12
    score: int | None = 3456
    queried: bool = True
    searched_limit: int = 2000


@dataclass(frozen=True)
class UnityPeak:
    current_j_rank: int = 3
    current_j_star: int = 2
    history_j_rank: int = 4
    history_j_star: int = 1
    current_j_win: int = 6
    current_j_all: int = 10
    current_k_rank: int = 2
    current_k_star: int = 5
    history_k_rank: int = 3
    history_k_star: int = 4
    current_k_win: int = 0
    current_k_all: int = 0
    current_z_score: int = 1234
    history_z_score: int = 2345
    current_z_win: int = 2
    current_z_all: int = 4


@dataclass(frozen=True)
class Empty:
    pass


class _LocalSummary:
    def __init__(
        self,
        rank_text: str = "",
        *,
        ranks: dict[str, str] | None = None,
    ) -> None:
        self._rank_text = rank_text
        self._ranks = ranks or {}

    def sample_rank(self, key: str) -> str:
        return self._ranks.get(key, self._rank_text)


def _rank_result(score: int, rank: int = 1) -> RankResult:
    return RankResult(score=score, rank=rank)


def _rank_summary() -> RankSummary:
    return RankSummary(
        book=_rank_result(1234),
        achieve=_rank_result(56),
        breakdown=RankBreakdown(
            pet_kind=_rank_result(100),
            skin=_rank_result(10),
            outfit_suit=_rank_result(20),
            outfit_part=_rank_result(30),
            mount=_rank_result(5),
            countermark=_rank_result(8),
            unlocked_count=173,
        ),
    )


def _peak_summary() -> PeakSummary:
    return PeakSummary(
        standard=PeakRank(rank=1),
        wild=PeakRank(rank=None),
        expert=PeakRank(rank=3),
    )


def _autocard_rank_summary(
    *,
    rank: int | None = 12,
    score: int | None = 3456,
    queried: bool = True,
    searched_limit: int = 2000,
) -> AutocardRankSummary:
    return AutocardRankSummary(
        rank=rank,
        score=score,
        queried=queried,
        searched_limit=searched_limit,
    )


def _unity_peak() -> UnityPeak:
    return UnityPeak()


def test_format_player_identity_team_vip_and_online_text() -> None:
    user_info = UserInfo(team_id=TEAM_ID, team_is_show=False, vip=1, vip_level=6)
    online_info = OnlineInfo(server_id=1, map_type=2, map_id=3)

    assert format_player_identity(PLAYER_ID, "赛小息") == "米米号：105023264（赛小息）"
    assert (
        format_team_text(user_info, "测试战队") == "测试战队（战队ID：987654321，隐藏）"
    )
    assert format_vip(user_info) == "是（等级：6）"
    assert format_online_text(online_info) == "在线（服务器：1，地图类型：2）"
    assert format_online_text(None) == "离线"


def test_format_login_timeline_orders_login_after_offline() -> None:
    user_info = UserInfo(
        login_time=1_780_000_000,
        last_offline_time=1_779_990_000,
    )
    online_info = OnlineInfo(server_id=1, map_type=2, map_id=3)

    assert format_login_timeline_lines(user_info, online_info) == [
        "最后离线：2026年5月29日 01:40:00",
        "最后登录：2026年5月29日 04:26:40",
        "是否在线：在线（服务器：1，地图类型：2）",
    ]


def test_format_login_timeline_orders_offline_after_login() -> None:
    user_info = UserInfo(
        login_time=1_779_990_000,
        last_offline_time=1_780_000_000,
    )
    online_info = OnlineInfo(server_id=1, map_type=2, map_id=3)

    assert format_login_timeline_lines(user_info, online_info) == [
        "最后登录：2026年5月29日 01:40:00",
        "最后离线：2026年5月29日 04:26:40",
        "是否在线：在线（服务器：1，地图类型：2）",
    ]


def test_format_login_timeline_keeps_online_info_as_source_of_truth() -> None:
    user_info = UserInfo(
        login_time=1_780_000_000,
        last_offline_time=1_779_990_000,
    )

    assert format_login_timeline_lines(user_info, None) == [
        "最后离线：2026年5月29日 01:40:00",
        "最后登录：2026年5月29日 04:26:40",
        "是否在线：离线",
    ]


def test_format_win_rate_handles_empty_and_non_empty_records() -> None:
    assert format_win_rate(0, 0) == "当前赛季未参赛"
    assert format_win_rate(2, 3) == "2/3=66.667%"


def test_format_compact_player_info_keeps_basic_sections_and_prompts() -> None:
    user_info = UserInfo(
        user_id=PLAYER_ID,
        nick="赛小息",
        vip=0,
        login_time=0,
        last_offline_time=0,
        team_id=0,
    )
    more_info = MoreInfo(reg_time=REG_TIME)

    message = format_compact_player_info(
        user_info,
        more_info,
        team_name="无",
        online_info=None,
        unity_peak=_as_any(Empty()),
        peak_rank_summary=_as_any(Empty()),
        local_summary=_as_any(_LocalSummary()),
        has_collection=True,
        has_peak=True,
        has_autocard=True,
        show_peak=False,
        extra_errors=["在线状态失败"],
    )

    assert "🤖【玩家信息】" in message
    assert "米米号：105023264（赛小息）" in message
    assert "注册时间：2000年1月1日 08:00:00" in message
    assert "战队：未加入" in message
    assert "回复“收集”查看收集与排行" in message
    assert "回复“巅峰”查看巅峰之战" in message
    assert "回复“群星牌”查看群星之巅排名" in message
    assert "在线状态失败" in message


def test_format_player_detail_messages_builds_collection_and_peak() -> None:
    user_info = UserInfo(nick="赛小息")
    more_info = MoreInfo(pet_all_num=321, total_achieve=56)
    unity_part_one = UnityPartOne(achievement_num=7, pet_kind_num=100, skin_num=10)

    messages = format_player_detail_messages(
        player_id=PLAYER_ID,
        user_info=user_info,
        more_info=more_info,
        unity_part_one=_as_any(unity_part_one),
        unity_peak=_as_any(_unity_peak()),
        rank_summary=_as_any(_rank_summary()),
        peak_rank_summary=_as_any(_peak_summary()),
        autocard_rank_summary=_as_any(_autocard_rank_summary()),
        local_rank_summary=_as_any(_LocalSummary("样本第1")),
        empty_local_rank_summary=_as_any(_LocalSummary()),
        has_collection=True,
        needs_peak_section=True,
        has_autocard_rank=True,
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
    assert "🃏【群星牌排名】" in messages.autocard_message
    assert "群星之巅：3456分" in messages.autocard_message
    assert "全服第12" in messages.autocard_message
    assert "样本第1" in messages.autocard_message
    assert "全服排行失败" in messages.collection_message
    assert "全服排行失败" in messages.peak_message
    assert "全服排行失败" in messages.autocard_message


def test_format_player_detail_messages_can_hide_local_rank_details() -> None:
    user_info = UserInfo(nick="赛小息")
    more_info = MoreInfo(pet_all_num=321, total_achieve=56)
    unity_part_one = UnityPartOne(achievement_num=7, pet_kind_num=100, skin_num=10)

    messages = format_player_detail_messages(
        player_id=PLAYER_ID,
        user_info=user_info,
        more_info=more_info,
        unity_part_one=_as_any(unity_part_one),
        unity_peak=_as_any(_unity_peak()),
        rank_summary=_as_any(_rank_summary()),
        peak_rank_summary=_as_any(_peak_summary()),
        autocard_rank_summary=_as_any(_autocard_rank_summary()),
        local_rank_summary=_as_any(_LocalSummary("样本第1")),
        empty_local_rank_summary=_as_any(_LocalSummary()),
        has_collection=True,
        needs_peak_section=False,
        has_autocard_rank=False,
        show_local_rank=False,
        extra_errors=[],
    )

    assert "样本第1" not in messages.collection_message
    assert messages.peak_message == ""
    assert messages.autocard_message == ""


def test_append_extra_errors_preserves_existing_message_when_empty() -> None:
    assert append_extra_errors("正文", []) == "正文"
    assert append_extra_errors("正文", ["A", "B"]) == "正文\n\n【扩展数据提示】\n\nA；B"
