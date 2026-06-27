from ironsbot.services.seer.rank_usage import build_rank_help_message


def test_rank_help_message_lists_core_rank_commands() -> None:
    message = build_rank_help_message()

    assert "📊【可用榜单】" in message
    assert "【全服图鉴榜】" in message
    assert "图鉴榜 / 成就榜 / 精灵榜 / 皮肤榜" in message
    assert "群星牌榜" in message
    assert "【刻印数值榜】" in message
    assert "别名：双刀=双攻，盾=双防。" in message
    assert "【巅峰样本榜】" in message
    assert "【本群管理】" in message
    assert "/榜单显示 20" in message
    assert "/缓存榜单 刻印榜 1-100" in message
