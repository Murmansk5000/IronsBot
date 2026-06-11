from types import SimpleNamespace

from pytest import MonkeyPatch

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.shared.features import service


def test_feature_service_reads_app_config_feature(
    monkeypatch: MonkeyPatch,
) -> None:
    feature_config = FeatureConfig(
        group_aliases={"main": 123},
        user_aliases={"owner": 456},
        group_policy={"main": ["seer"]},
        user_policy={"owner": ["ai_chat"]},
        superuser_bypass=False,
    )
    monkeypatch.setattr(
        service,
        "get_app_config",
        lambda: SimpleNamespace(feature=feature_config),
    )

    feature_service = service.FeatureService()

    assert feature_service.groups_for_feature("seer") == [123]
    assert feature_service.users_for_feature("ai_chat") == [456]
    assert feature_service.resolve_group_policy(123) == ["seer"]
    assert feature_service.resolve_user_policy(456) == ["ai_chat"]
    assert feature_service.is_group_feature_allowed(999, 123, "seer")
    assert not feature_service.is_group_feature_allowed(999, 123, "text")
