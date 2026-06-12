from ironsbot.services.seer.rank_usage import build_rank_help_message


def test_rank_help_message_lists_core_rank_commands() -> None:
    message = build_rank_help_message()

    assert "📊【可用榜单】" in message
    assert "图鉴榜 / 图鉴积分榜" in message
    assert "样本竞技段位榜 / 样本竞技胜率榜" in message
    assert "/缓存榜单 刻印榜 1-100" in message
