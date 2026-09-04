import logging
from dataclasses import dataclass
from typing import Any, cast

import pytest

from ironsbot.services.seer.player_collection_formatting import (
    format_autocard_rank_info,
)
from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_formatting_common import (
    format_login_timeline_lines,
    format_online_text,
    format_player_identity,
    format_team_text,
    format_vip,
    format_win_rate,
)
from ironsbot.services.seer.player_peak_formatting import (
    format_compact_peak_section,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    RankLookupResult,
)

PLAYER_ID = 712345678
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


def test_format_player_identity_team_vip_and_online_text() -> None:
    user_info = UserInfo(team_id=TEAM_ID, team_is_show=False, vip=1, vip_level=6)
    online_info = OnlineInfo(server_id=1, map_type=2, map_id=3)

    assert format_player_identity(PLAYER_ID, "赛小息") == "米米号：712345678（赛小息）"
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


def test_format_peak_uses_current_season_rank_instead_of_stale_forever_value() -> None:
    peak = UnityPeak(
        current_j_rank=4,
        current_j_star=0,
        current_j_win=82,
        current_j_all=124,
    )
    summary = PeakSeasonRankSummary(
        standard=RankLookupResult(
            title="竞技赛季榜",
            score_name="段位分",
            rank=1,
            score=300033,
            queried=True,
        ),
        wild=RankLookupResult(
            title="狂野赛季榜",
            score_name="段位分",
            searched_limit=2000,
            queried=True,
        ),
        expert=RankLookupResult(
            title="专家赛季榜",
            score_name="专家积分",
            searched_limit=2000,
            queried=True,
        ),
    )

    message = format_compact_peak_section(
        _as_any(peak),
        summary,
        _as_any(_LocalSummary()),
    )

    assert message.splitlines()[1].startswith("获取时间：")
    assert "竞技：王者33星" in message
    assert "竞技：圣皇0星" not in message
    assert "场次124" not in message
    assert "狂野：当前赛季前2000名未确认" in message


def test_peak_logs_when_rank_confirmation_hides_successful_profile_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    peak = UnityPeak(
        current_k_rank=0,
        current_k_star=41,
        current_k_win=10,
        current_k_all=10,
    )
    summary = PeakSeasonRankSummary.empty()
    summary.wild.queried = True
    summary.wild.searched_limit = 20_000
    summary.wild.query_id = "wild-rank-test"
    with caplog.at_level(logging.INFO):
        message = format_compact_peak_section(
            _as_any(peak),
            summary,
            _as_any(_LocalSummary()),
            player_id=PLAYER_ID,
            query_id="peak-base-test",
        )
    assert "狂野：当前赛季前20000名未确认" in message
    wild_line = next(line for line in message.splitlines() if line.startswith("狂野："))
    assert "场次10" in wild_line
    assert "胜率10/10=100.000%" in wild_line
    record = next(
        record.getMessage()
        for record in caplog.records
        if "mode=wild" in record.getMessage()
    )
    assert "query=peak-base-test" in record
    assert "profile_available=True profile_score=41" in record
    assert "rank_query=wild-rank-test rank=None" in record
    assert "selected=当前赛季前20000名未确认" in record


def test_format_peak_shows_rank_failure_on_the_affected_mode_line() -> None:
    peak = UnityPeak(
        current_j_rank=4,
        current_j_star=0,
        current_j_win=33,
        current_j_all=41,
    )
    summary = PeakSeasonRankSummary.empty()
    summary.standard.failure = "查询超时"

    message = format_compact_peak_section(
        _as_any(peak),
        summary,
        _as_any(_LocalSummary()),
    )

    standard_line = next(
        line for line in message.splitlines() if line.startswith("竞技：")
    )
    assert "赛季榜查询超时" in standard_line
    assert "赛季榜未上榜" not in standard_line
    assert "场次41" in standard_line
    assert "胜率33/41=80.488%" in standard_line


def test_format_peak_does_not_report_unqueried_mode_as_unranked() -> None:
    peak = UnityPeak(current_z_score=1421, current_z_all=38)

    message = format_compact_peak_section(
        _as_any(peak),
        PeakSeasonRankSummary.empty(),
        _as_any(_LocalSummary()),
    )

    expert_line = next(
        line for line in message.splitlines() if line.startswith("专家：")
    )
    assert "赛季榜未查询" in expert_line
    assert "赛季榜未上榜" not in expert_line


def test_format_peak_keeps_successful_mode_when_another_mode_times_out() -> None:
    peak = UnityPeak(
        current_z_score=1209,
        history_z_score=1437,
        current_z_win=8,
        current_z_all=9,
    )
    summary = PeakSeasonRankSummary.empty()
    summary.expert.rank = 143
    summary.expert.score = 1209
    summary.expert.queried = True

    message = format_compact_peak_section(
        _as_any(peak),
        summary,
        _as_any(_LocalSummary()),
        available_modes=frozenset(("expert",)),
        mode_errors={"standard": "查询超时", "wild": "查询未完成"},
    )

    standard_line = next(
        line for line in message.splitlines() if line.startswith("竞技：")
    )
    wild_line = next(
        line for line in message.splitlines() if line.startswith("狂野：")
    )
    expert_line = next(
        line for line in message.splitlines() if line.startswith("专家：")
    )
    assert "当前暂未获取（查询超时）" in standard_line
    assert "历史暂未获取（查询超时）" in standard_line
    assert "学徒0星" not in standard_line
    assert "当前暂未获取（查询未完成）" in wild_line
    assert "专家：1209分" in expert_line
    assert "历史1437分" in expert_line
    assert "赛季榜第143" in expert_line


def test_format_peak_does_not_turn_a_first_packet_timeout_into_zero_values() -> None:
    message = format_compact_peak_section(
        _as_any(UnityPeak()),
        PeakSeasonRankSummary.empty(),
        _as_any(_LocalSummary()),
        available_modes=frozenset(),
        mode_errors={
            "standard": "查询超时",
            "wild": "查询未完成",
            "expert": "查询未完成",
        },
    )

    assert "竞技：当前暂未获取（查询超时）" in message
    assert "狂野：当前暂未获取（查询未完成）" in message
    assert "专家：当前暂未获取（查询未完成）" in message
    assert "学徒0星" not in message
    assert "历史0分" not in message


def test_format_autocard_rank_starts_with_fetch_time() -> None:
    message = format_autocard_rank_info(
        RankLookupResult(
            title="群星之巅榜",
            score_name="分",
            rank=15,
            score=9525,
            queried=True,
        ),
        player_identity="米米号：1269554（XJTLoveness）",
        local_summary=_as_any(_LocalSummary()),
    )

    assert message.splitlines()[1].startswith("获取时间：")


def test_format_autocard_rank_marks_cached_fallback_after_timeout() -> None:
    message = format_autocard_rank_info(
        RankLookupResult(
            title="群星之巅榜",
            score_name="分",
            rank=15,
            score=9525,
            failure="查询超时",
            fallback_cached_at=REG_TIME,
        ),
        player_identity="米米号：1269554（XJTLoveness）",
        local_summary=_as_any(_LocalSummary()),
    )

    assert "9525分" in message
    assert "前 15 名未上榜" not in message
    assert "缓存于2000年1月1日 08:00:00，本次查询超时" in message


def test_format_compact_player_info_keeps_basic_sections_and_errors() -> None:
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
        show_peak=False,
        extra_errors=["在线状态失败"],
    )

    assert "🤖【玩家信息】" in message
    assert "米米号：712345678（赛小息）" in message
    assert "注册时间：2000年1月1日 08:00:00" in message
    assert "战队：未加入" in message
    assert "在线状态失败" in message
    assert "\n\n" not in message
