from ironsbot.services.seer.player_query import (
    PlayerDetailFetchPlan,
    PlayerDetailMessages,
    PlayerQuerySectionPlan,
    extract_player_query_arg,
    plan_player_detail_fetches,
    plan_player_query_sections,
    player_detail_commands,
    player_detail_empty_message,
    player_detail_failure_message,
    player_detail_pending_message,
    player_detail_timeout_message,
    player_query_failure_message,
    player_query_in_progress_message,
    player_query_timeout_message,
    player_query_wait_message,
)


def test_extract_player_query_arg_reads_known_prefixes() -> None:
    assert extract_player_query_arg("米米号 105023264") == "105023264"
    assert extract_player_query_arg("查询玩家信息105023264") == "105023264"
    assert extract_player_query_arg("  米米号\t123 ") == "123"


def test_extract_player_query_arg_ignores_unrelated_text() -> None:
    assert extract_player_query_arg("查询战队 123") is None
    assert extract_player_query_arg("105023264") is None


def test_player_query_messages_explain_slow_sections() -> None:
    in_progress = player_query_in_progress_message(105023264)
    wait = player_query_wait_message(30)

    assert "正在查询米米号 105023264" in in_progress
    assert "请 30 秒后再试" in wait
    assert "收集、巅峰和全服排行数据会更慢" in wait
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


def test_plan_player_query_sections_maps_configured_sections() -> None:
    plan = plan_player_query_sections(
        ("basic", "collection", "local_rank", "peak"),
        local_rank_enabled=True,
    )

    assert plan == PlayerQuerySectionPlan(
        show_local_rank=True,
        has_collection=True,
        needs_peak_section=True,
        needs_online_info=True,
        local_rank_enabled=True,
    )
    assert plan.needs_detail_task is True


def test_plan_player_query_sections_keeps_cache_refresh_detail_task() -> None:
    plan = plan_player_query_sections(("basic",), local_rank_enabled=True)

    assert plan.show_local_rank is False
    assert plan.has_collection is False
    assert plan.needs_peak_section is False
    assert plan.needs_online_info is True
    assert plan.needs_detail_task is True


def test_player_detail_commands_follow_available_detail_sections() -> None:
    assert player_detail_commands(has_collection=True, has_peak=True) == (
        "收集",
        "巅峰",
    )
    assert player_detail_commands(has_collection=False, has_peak=True) == ("巅峰",)
    assert player_detail_commands(has_collection=False, has_peak=False) == ()


def test_plan_player_detail_fetches_for_collection_and_peak() -> None:
    assert plan_player_detail_fetches(
        has_collection=True,
        needs_peak_section=True,
        local_rank_enabled=False,
    ) == PlayerDetailFetchPlan(
        needs_unity_part_one=True,
        needs_unity_peak=True,
        needs_rank_summary=True,
        needs_local_rank=False,
    )


def test_plan_player_detail_fetches_expands_for_local_rank_cache_update() -> None:
    assert plan_player_detail_fetches(
        has_collection=False,
        needs_peak_section=False,
        local_rank_enabled=True,
    ) == PlayerDetailFetchPlan(
        needs_unity_part_one=True,
        needs_unity_peak=True,
        needs_rank_summary=True,
        needs_local_rank=True,
    )


def test_plan_player_detail_fetches_can_skip_all_optional_fetches() -> None:
    assert plan_player_detail_fetches(
        has_collection=False,
        needs_peak_section=False,
        local_rank_enabled=False,
    ) == PlayerDetailFetchPlan(
        needs_unity_part_one=False,
        needs_unity_peak=False,
        needs_rank_summary=False,
        needs_local_rank=False,
    )
