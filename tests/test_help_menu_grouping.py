from ironsbot.plugins.help import HELP_ENTRY_ORDER, HELP_GROUP_TITLES


def test_team_entries_are_grouped_with_seer_queries() -> None:
    assert HELP_GROUP_TITLES["ai"] == "AI"
    assert HELP_ENTRY_ORDER["AI聊天"][0] == "ai"
    assert HELP_ENTRY_ORDER["AI意图分析"][0] == "ai"
    assert HELP_ENTRY_ORDER["战队推荐"][0] == "seer"
    assert HELP_ENTRY_ORDER["战队资源订阅"][0] == "seer"
    assert HELP_ENTRY_ORDER["战队审核入群提示"][0] == "seer"
    assert HELP_ENTRY_ORDER["开服查询"][0] == "seer"
