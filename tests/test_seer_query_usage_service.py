from ironsbot.config.models.feature import FeatureConfig
from ironsbot.services.seer import query_usage
from ironsbot.shared.features import FeatureService
from tests.helpers.onebot_events import group_message_event


def _features(*allowed: str) -> FeatureService:
    return FeatureService(
        FeatureConfig(
            group_policy={"456": list(allowed)},
            superuser_bypass=False,
        ),
        frozenset(),
    )


def test_seer_query_usage_message_only_lists_allowed_sections() -> None:
    message = query_usage.build_seer_query_usage_message(
        _features("seer_player", "seer_rank"),
        group_message_event(),
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
        _features(),
        group_message_event(),
    ) == "当前会话没有可用的赛尔号查询子功能。"
