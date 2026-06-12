from ironsbot.services.seer.player_query import (
    PlayerDetailMessages,
    extract_player_query_arg,
    player_detail_pending_message,
    player_query_in_progress_message,
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


def test_player_detail_pending_message_mentions_label() -> None:
    message = player_detail_pending_message("收集与排行")

    assert "收集与排行还在查询中" in message
    assert "全服榜或赛季榜数据" in message


def test_player_detail_messages_defaults_to_empty_messages() -> None:
    messages = PlayerDetailMessages()

    assert messages.collection_message == ""
    assert messages.peak_message == ""
