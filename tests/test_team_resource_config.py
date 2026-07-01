import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from ironsbot.config.models.seer import TeamResourceConfig

ROOT = Path(__file__).resolve().parents[1]
TEAM_RESOURCE_THRESHOLD = 2000


def _load_team_resource_config_module():
    spec = spec_from_file_location(
        "team_resource_config_for_test",
        ROOT / "ironsbot" / "plugins" / "team_shortcut" / "config.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _app_config(team_resource: TeamResourceConfig) -> SimpleNamespace:
    return SimpleNamespace(
        feature=SimpleNamespace(
            group_aliases={"anjie": 786252348},
            user_aliases={"owner": 1234567890},
        ),
        seer=SimpleNamespace(team_resource=team_resource),
    )


def test_team_resource_subscription_resolves_aliases(
    monkeypatch: MonkeyPatch,
) -> None:
    config = TeamResourceConfig(
        subscriptions=[
            {
                "group": "anjie",
                "team_ids": [1234567, 2345678],
                "threshold": TEAM_RESOURCE_THRESHOLD,
                "at_users": ["owner", "2345678901"],
            }
        ]
    )
    team_resource_config = _load_team_resource_config_module()
    monkeypatch.setattr(
        team_resource_config,
        "get_app_config",
        lambda: _app_config(config),
    )

    subscriptions = team_resource_config.subscriptions_for_group(786252348)

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
        subscriptions=[
            {
                "group": "anjie",
                "team_ids": [1234567],
            }
        ],
    )
    team_resource_config = _load_team_resource_config_module()
    monkeypatch.setattr(
        team_resource_config,
        "get_app_config",
        lambda: _app_config(config),
    )

    assert team_resource_config.get_team_resource_subscriptions() == []
