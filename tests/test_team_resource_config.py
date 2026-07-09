import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.seer import (
    TeamResourceConfig,
    TeamResourceSubscriptionConfig,
)
from tests.helpers.config import stub_app_config

ROOT = Path(__file__).resolve().parents[1]
TEAM_RESOURCE_THRESHOLD = 2000


def _load_team_resource_config_module():
    spec = spec_from_file_location(
        "team_resource_config_for_test",
        ROOT / "ironsbot" / "plugins" / "team_resource_subscription" / "config.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _app_config(team_resource: TeamResourceConfig):
    return stub_app_config(
        feature_config=FeatureConfig(
            group_aliases={"example": 987654321},
            user_aliases={"owner": 1234567890},
        ),
        team_resource_config=team_resource,
    )


def test_team_resource_subscription_resolves_aliases(
    monkeypatch: MonkeyPatch,
) -> None:
    config = TeamResourceConfig(
        subscriptions=cast(
            "list[TeamResourceSubscriptionConfig]",
            [
                {
                    "group": "example",
                    "team_ids": [1234567, 2345678],
                    "threshold": TEAM_RESOURCE_THRESHOLD,
                    "at_users": ["owner", "2345678901"],
                }
            ],
        )
    )
    team_resource_config = _load_team_resource_config_module()
    monkeypatch.setattr(
        team_resource_config,
        "get_app_config",
        lambda: _app_config(config),
    )

    subscriptions = team_resource_config.subscriptions_for_group(987654321)

    assert len(subscriptions) == 1
    assert subscriptions[0].team_ids == [1234567, 2345678]
    assert subscriptions[0].threshold == TEAM_RESOURCE_THRESHOLD
    assert team_resource_config.at_users_for_subscription(subscriptions[0]) == [
        1234567890,
        2345678901,
    ]


def test_team_resource_disabled_has_no_subscriptions(
    monkeypatch: MonkeyPatch,
) -> None:
    config = TeamResourceConfig(
        enabled=False,
        subscriptions=cast(
            "list[TeamResourceSubscriptionConfig]",
            [
                {
                    "group": "example",
                    "team_ids": [1234567],
                }
            ],
        ),
    )
    team_resource_config = _load_team_resource_config_module()
    monkeypatch.setattr(
        team_resource_config,
        "get_app_config",
        lambda: _app_config(config),
    )

    assert team_resource_config.get_team_resource_subscriptions() == []
