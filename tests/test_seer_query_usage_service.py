from pytest import MonkeyPatch

from ironsbot.services.seer import query_usage


def test_seer_query_usage_message_only_lists_allowed_sections(
    monkeypatch: MonkeyPatch,
) -> None:
    allowed = {"seer_player", "seer_rank"}
    monkeypatch.setattr(
        query_usage,
        "feature_visible_for_help",
        lambda _event, feature: feature in allowed,
    )

    message = query_usage.build_seer_query_usage_message(object())  # type: ignore[arg-type]

    assert "【玩家】" in message
    assert "【榜单入口】" in message
    assert "【精灵、技能、魂印、立绘、皮肤】" not in message
    assert "皮肤雷伊" not in message
    assert "【刻印、宝石、刻印榜】" not in message


def test_seer_query_usage_message_reports_no_available_sections(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_usage,
        "feature_visible_for_help",
        lambda _event, _feature: False,
    )

    assert (
        query_usage.build_seer_query_usage_message(object())  # type: ignore[arg-type]
        == "当前会话没有可用的赛尔号查询子功能。"
    )
