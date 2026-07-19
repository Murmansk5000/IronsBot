import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass

from ironsbot.services.seer.player_query import (
    PLAYER_AUTOCARD_KEY,
    PLAYER_COLLECTION_KEY,
    PLAYER_DETAIL_AUTO_REPLY_KEYS,
    PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY,
    PLAYER_PEAK_KEY,
    PlayerDetailFetchPlan,
    PlayerDetailMessages,
    PlayerDetailPromptPlan,
    PlayerDetailReplyRequest,
    PlayerPeakScores,
    PlayerQuerySectionPlan,
    cached_player_detail_message,
    calculate_player_peak_scores,
    extract_player_query_arg,
    optional_player_extra,
    plan_player_detail_fetches,
    plan_player_detail_prompt,
    plan_player_query_sections,
    player_detail_auto_reply_keys,
    player_detail_auto_reply_tasks,
    player_detail_commands,
    player_detail_empty_message,
    player_detail_failure_message,
    player_detail_pending_message,
    player_detail_timeout_message,
    player_query_failure_message,
    player_query_timeout_message,
    resolve_player_detail_reply,
    safe_player_extra,
    store_player_detail_messages,
    validate_player_peak_season,
)
from ironsbot.services.seer.player_shortcuts import parse_player_shortcut_command
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    RankLookupResult,
)
from ironsbot.services.seer.rank_peak import build_peak_rating_score
from ironsbot.services.seer.sequ_extra import UnityPeakInfo

EXPERT_MATCH_COUNT = 113


@dataclass(frozen=True, slots=True)
class FakeUnityPeak:
    current_j_rank: int
    current_j_star: int
    current_j_all: int
    current_k_rank: int
    current_k_star: int
    current_k_all: int
    current_z_score: int
    current_z_all: int


def test_extract_player_query_arg_reads_known_prefixes() -> None:
    assert extract_player_query_arg("米米号 105023264") == "105023264"
    assert extract_player_query_arg("查询玩家信息105023264") == "105023264"
    assert extract_player_query_arg("  米米号\t123 ") == "123"


def test_extract_player_query_arg_ignores_unrelated_text() -> None:
    assert extract_player_query_arg("查询战队 123") is None
    assert extract_player_query_arg("105023264") is None


def test_parse_player_shortcuts_supports_bound_and_explicit_queries() -> None:
    collection = parse_player_shortcut_command("收集")
    peak = parse_player_shortcut_command("巅峰 105023264")
    autocard = parse_player_shortcut_command("群星牌105023264")

    assert collection is not None
    assert (collection.kind, collection.player_id) == ("collection", None)
    assert peak is not None
    assert (peak.kind, peak.player_id) == ("peak", 105023264)
    assert autocard is not None
    assert (autocard.kind, autocard.player_id) == ("autocard", 105023264)


def test_parse_player_shortcuts_does_not_take_named_autocard_queries() -> None:
    assert parse_player_shortcut_command("群星牌地葬") is None
    assert parse_player_shortcut_command("群星牌卡98") is None


def test_player_query_error_messages_include_player_id() -> None:
    assert player_query_timeout_message(105023264) == (
        "❌ 米米号 105023264 查询超时，请稍后再试。"
    )
    assert player_query_failure_message(105023264, "boom") == (
        "❌ 米米号 105023264 查询失败：boom"
    )


def test_player_detail_pending_message_mentions_label() -> None:
    message = player_detail_pending_message("收集与排行")

    assert "收集与排行还在查询中" in message
    assert "全服榜或赛季榜数据" in message
    assert player_detail_timeout_message("收集与排行") == (
        "❌ 收集与排行数据查询超时，请稍后再试。"
    )
    assert player_detail_failure_message("收集与排行", "boom") == (
        "❌ 收集与排行数据获取失败：boom"
    )
    assert player_detail_empty_message("收集与排行") == (
        "❌ 收集与排行数据没有返回结果，请稍后再试。"
    )


def test_player_detail_messages_defaults_to_empty_messages() -> None:
    messages = PlayerDetailMessages()

    assert messages.collection_message == ""
    assert messages.peak_message == ""
    assert messages.autocard_message == ""


def test_resolve_player_detail_reply_maps_text_to_detail_request() -> None:
    assert resolve_player_detail_reply("收集") == PlayerDetailReplyRequest(
        key=PLAYER_COLLECTION_KEY,
        label="收集与排行",
    )
    assert resolve_player_detail_reply(" 巅 峰 ") == PlayerDetailReplyRequest(
        key=PLAYER_PEAK_KEY,
        label="巅峰之战",
    )
    assert resolve_player_detail_reply("群星牌") == PlayerDetailReplyRequest(
        key=PLAYER_AUTOCARD_KEY,
        label="群星牌排名",
    )
    assert resolve_player_detail_reply("战队") is None


def test_store_and_read_cached_player_detail_messages() -> None:
    state: dict[str, object] = {}

    store_player_detail_messages(
        state,
        PlayerDetailMessages(
            collection_message="collection",
            peak_message="peak",
            autocard_message="autocard",
        ),
    )

    assert cached_player_detail_message(state, PLAYER_COLLECTION_KEY) == "collection"
    assert cached_player_detail_message(state, PLAYER_PEAK_KEY) == "peak"
    assert cached_player_detail_message(state, PLAYER_AUTOCARD_KEY) == "autocard"
    assert cached_player_detail_message(state, "missing") == ""


def test_player_detail_auto_reply_state_sets_are_created_once() -> None:
    state: dict[str, object] = {}

    keys = player_detail_auto_reply_keys(state)
    tasks = player_detail_auto_reply_tasks(state)
    keys.add("collection")
    tasks.add("task")

    assert player_detail_auto_reply_keys(state) is keys
    assert player_detail_auto_reply_tasks(state) is tasks
    assert state[PLAYER_DETAIL_AUTO_REPLY_KEYS] == {"collection"}
    assert state[PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY] == {"task"}


def test_build_peak_rating_score_matches_rank_score_shape() -> None:
    rank_seven_star_three_score = 700003
    star_only_score = 5

    assert build_peak_rating_score(7, 3) == rank_seven_star_three_score
    assert build_peak_rating_score(0, 5) == star_only_score
    assert build_peak_rating_score(0, 0) is None


def test_calculate_player_peak_scores_uses_only_played_modes() -> None:
    unity_peak = FakeUnityPeak(
        current_j_rank=7,
        current_j_star=3,
        current_j_all=10,
        current_k_rank=5,
        current_k_star=2,
        current_k_all=0,
        current_z_score=1234,
        current_z_all=6,
    )

    assert calculate_player_peak_scores(unity_peak) == PlayerPeakScores(
        standard=700003,
        wild=None,
        expert=1234,
    )


def test_calculate_player_peak_scores_defaults_missing_fields_to_empty_scores() -> None:
    assert calculate_player_peak_scores(object()) == PlayerPeakScores()


def test_validate_player_peak_season_replaces_stale_scores_and_stats() -> None:
    unity_peak = UnityPeakInfo(
        current_j_rank=4,
        current_j_star=0,
        current_j_win=82,
        current_j_all=124,
        current_k_rank=3,
        current_k_star=100,
        current_k_win=724,
        current_k_all=1623,
        current_z_score=1045,
        current_z_win=50,
        current_z_all=EXPERT_MATCH_COUNT,
    )
    candidate_scores = calculate_player_peak_scores(unity_peak)
    rank_summary = PeakSeasonRankSummary(
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
            rank=2,
            score=1045,
            queried=True,
        ),
    )

    validated = validate_player_peak_season(
        unity_peak,
        candidate_scores,
        rank_summary,
    )

    assert validated.scores == PlayerPeakScores(
        standard=300033,
        wild=None,
        expert=1045,
    )
    assert validated.unity_peak.current_j_all == 0
    assert validated.unity_peak.current_k_all == 0
    assert validated.unity_peak.current_z_all == EXPERT_MATCH_COUNT
    assert "peak_standard" not in validated.clear_metric_keys
    assert "peak_standard_matches" in validated.clear_metric_keys
    assert "peak_wild" in validated.clear_metric_keys
    assert "peak_total_matches" in validated.clear_metric_keys


def test_safe_player_extra_returns_result() -> None:
    async def run() -> str:
        return "ok"

    extra_errors: list[str] = []

    assert (
        asyncio.run(safe_player_extra("在线状态", run(), "fallback", extra_errors))
        == "ok"
    )
    assert extra_errors == []


def test_safe_player_extra_records_timeout_as_readable_error() -> None:
    async def run() -> str:
        await asyncio.sleep(0.05)
        return "unused"

    extra_errors: list[str] = []

    assert (
        asyncio.run(
            safe_player_extra(
                "群星牌排行",
                run(),
                "fallback",
                extra_errors,
                timeout_seconds=0.001,
            )
        )
        == "fallback"
    )
    assert extra_errors == ["群星牌排行失败：查询超时"]


def test_safe_player_extra_uses_dynamic_error_label() -> None:
    async def run() -> str:
        await asyncio.sleep(0.05)
        return "unused"

    extra_errors: list[str] = []
    logged_labels: list[str] = []

    assert (
        asyncio.run(
            safe_player_extra(
                "全服排行",
                run(),
                "fallback",
                extra_errors,
                timeout_seconds=0.001,
                error_label_factory=lambda: "刻印图鉴榜",
                on_error=lambda label, _error: logged_labels.append(label),
            )
        )
        == "fallback"
    )
    assert extra_errors == ["刻印图鉴榜失败：查询超时"]
    assert logged_labels == ["刻印图鉴榜"]


def test_optional_player_extra_skips_disabled_factory() -> None:
    called = False

    async def run() -> str:
        return "unused"

    def factory() -> Awaitable[str]:
        nonlocal called
        called = True
        return run()

    extra_errors: list[str] = []

    assert (
        asyncio.run(
            optional_player_extra(
                "在线状态",
                enabled=False,
                awaitable_factory=factory,
                default="fallback",
                extra_errors=extra_errors,
            )
        )
        == "fallback"
    )
    assert called is False
    assert extra_errors == []


def test_optional_player_extra_records_errors_and_uses_logger_callback() -> None:
    async def fail() -> str:
        msg = "boom"
        raise RuntimeError(msg)

    extra_errors: list[str] = []
    logged_errors: list[tuple[str, str]] = []

    assert (
        asyncio.run(
            optional_player_extra(
                "在线状态",
                enabled=True,
                awaitable_factory=fail,
                default="fallback",
                extra_errors=extra_errors,
                on_error=lambda label, error: logged_errors.append(
                    (label, str(error))
                ),
            )
        )
        == "fallback"
    )
    assert extra_errors == ["在线状态失败：boom"]
    assert logged_errors == [("在线状态", "boom")]


def test_plan_player_query_sections_maps_configured_sections() -> None:
    plan = plan_player_query_sections(
        ("basic", "collection", "local_rank", "peak", "autocard"),
        local_rank_enabled=True,
    )

    assert plan == PlayerQuerySectionPlan(
        show_local_rank=True,
        has_collection=True,
        needs_peak_section=True,
        has_autocard_rank=True,
        needs_online_info=True,
        local_rank_enabled=True,
    )
    assert plan.needs_detail_task is True


def test_plan_player_query_sections_keeps_cache_refresh_detail_task() -> None:
    plan = plan_player_query_sections(("basic",), local_rank_enabled=True)

    assert plan.show_local_rank is False
    assert plan.has_collection is False
    assert plan.needs_peak_section is False
    assert plan.has_autocard_rank is False
    assert plan.needs_online_info is True
    assert plan.needs_detail_task is True


def test_player_detail_commands_follow_available_detail_sections() -> None:
    assert player_detail_commands(
        has_collection=True,
        has_peak=True,
        has_autocard=True,
    ) == (
        "收集",
        "巅峰",
        "群星牌",
    )
    assert player_detail_commands(
        has_collection=False,
        has_peak=True,
        has_autocard=False,
    ) == ("巅峰",)
    assert player_detail_commands(
        has_collection=False,
        has_peak=False,
        has_autocard=False,
    ) == ()


def test_plan_player_detail_prompt_enters_available_conversation() -> None:
    assert plan_player_detail_prompt(
        has_collection=True,
        has_peak=True,
        has_autocard=True,
        supports_conversation=True,
    ) == PlayerDetailPromptPlan(
        commands=("收集", "巅峰", "群星牌"),
        should_enter_conversation=True,
    )


def test_plan_player_detail_prompt_finishes_when_no_commands_are_available() -> None:
    assert plan_player_detail_prompt(
        has_collection=False,
        has_peak=False,
        has_autocard=False,
        supports_conversation=True,
    ) == PlayerDetailPromptPlan(
        commands=(),
        should_enter_conversation=False,
    )


def test_plan_player_detail_prompt_keeps_commands_without_event() -> None:
    assert plan_player_detail_prompt(
        has_collection=False,
        has_peak=True,
        has_autocard=False,
        supports_conversation=False,
    ) == PlayerDetailPromptPlan(
        commands=("巅峰",),
        should_enter_conversation=False,
    )


def test_plan_player_detail_fetches_for_collection_and_peak() -> None:
    assert plan_player_detail_fetches(
        has_collection=True,
        needs_peak_section=True,
        has_autocard_rank=True,
        local_rank_enabled=False,
    ) == PlayerDetailFetchPlan(
        needs_unity_part_one=True,
        needs_unity_peak=True,
        needs_rank_summary=True,
        needs_autocard_rank=True,
        needs_local_rank=False,
    )


def test_plan_player_detail_fetches_expands_for_local_rank_cache_update() -> None:
    assert plan_player_detail_fetches(
        has_collection=False,
        needs_peak_section=False,
        has_autocard_rank=False,
        local_rank_enabled=True,
    ) == PlayerDetailFetchPlan(
        needs_unity_part_one=True,
        needs_unity_peak=True,
        needs_rank_summary=True,
        needs_autocard_rank=False,
        needs_local_rank=True,
    )


def test_plan_player_detail_fetches_can_skip_all_optional_fetches() -> None:
    assert plan_player_detail_fetches(
        has_collection=False,
        needs_peak_section=False,
        has_autocard_rank=False,
        local_rank_enabled=False,
    ) == PlayerDetailFetchPlan(
        needs_unity_part_one=False,
        needs_unity_peak=False,
        needs_rank_summary=False,
        needs_autocard_rank=False,
        needs_local_rank=False,
    )
