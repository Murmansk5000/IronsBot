from ironsbot.services.seer import query_usage


def test_seer_query_usage_message_only_lists_allowed_sections() -> None:
    message = query_usage.build_seer_query_usage_message(
        {"seer_player", "seer_rank"}.__contains__,
    )

    assert "【玩家】" in message
    assert "绑定米米号123456" in message
    assert "【榜单入口】" in message
    assert "成就榜123456" in message
    assert "【精灵、技能、魂印、立绘、皮肤】" not in message
    assert "【刻印、宝石、刻印榜】" not in message
    assert "feature:" not in message


def test_seer_query_usage_message_reports_no_available_sections() -> None:
    assert query_usage.build_seer_query_usage_message(
        set().__contains__,
    ) == "当前会话没有可用的赛尔号查询子功能。"
