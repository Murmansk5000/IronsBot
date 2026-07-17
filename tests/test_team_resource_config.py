import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from pytest import MonkeyPatch

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.services.team_resource_subscriptions import (
    TeamResourceSubscriptionStore,
    TeamResourceSubscriptionUpdate,
)
from tests.helpers.config import stub_app_config

ROOT = Path(__file__).resolve().parents[1]
TEAM_ID = 1234567
TEAM_RESOURCE_THRESHOLD = 2000
OWNER_ID = 1234567890
ADMIN_ID = 2345678901


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


def test_team_resource_subscription_store_is_used_for_group(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = TeamResourceConfig(
        subscription_path=tmp_path / "team_resource.sqlite",
        default_at_users=["owner", "2345678901"],
    )
    team_resource_config = _load_team_resource_config_module()
    monkeypatch.setattr(
        team_resource_config,
        "get_app_config",
        lambda: _app_config(config),
    )

    team_resource_config.get_team_resource_store().upsert(
        TeamResourceSubscriptionUpdate(
            group_id=987654321,
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
            at_user_ids=(OWNER_ID, ADMIN_ID),
            operator_id=OWNER_ID,
        )
    )

    subscriptions = team_resource_config.subscriptions_for_group(987654321)

    assert len(subscriptions) == 1
    assert subscriptions[0].team_id == TEAM_ID
    assert subscriptions[0].threshold == TEAM_RESOURCE_THRESHOLD
    assert team_resource_config.at_users_for_subscription(subscriptions[0]) == [
        OWNER_ID,
        ADMIN_ID,
    ]
    assert team_resource_config.default_at_user_ids() == (
        OWNER_ID,
        ADMIN_ID,
    )


def test_team_resource_disabled_has_no_subscriptions(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = TeamResourceConfig(
        enabled=False,
        subscription_path=tmp_path / "team_resource.sqlite",
    )
    team_resource_config = _load_team_resource_config_module()
    monkeypatch.setattr(
        team_resource_config,
        "get_app_config",
        lambda: _app_config(config),
    )

    assert team_resource_config.get_team_resource_subscriptions() == []


def test_team_resource_store_tracks_group_prompt_once(tmp_path: Path) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "team_resource.sqlite")

    assert not store.has_prompted_group(987654321)
    assert store.get_pending_prompt(987654321) is None

    store.mark_group_prompted(
        group_id=987654321,
        team_id=TEAM_ID,
        team_name="示例战队",
        prompted_by=OWNER_ID,
    )

    prompt = store.get_pending_prompt(987654321)
    assert prompt is not None
    assert store.has_prompted_group(987654321)
    assert prompt.team_id == TEAM_ID
    assert prompt.team_name == "示例战队"
    assert prompt.prompted_by == OWNER_ID

    store.mark_group_prompted(
        group_id=987654321,
        team_id=7654321,
        team_name="另一个战队",
        prompted_by=ADMIN_ID,
    )
    assert store.get_pending_prompt(987654321) == prompt


def test_team_resource_prompt_can_be_marked_handled(tmp_path: Path) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "team_resource.sqlite")
    store.mark_group_prompted(
        group_id=987654321,
        team_id=TEAM_ID,
        team_name="示例战队",
        prompted_by=OWNER_ID,
    )

    store.mark_prompt_handled(
        group_id=987654321,
        handled_by=ADMIN_ID,
        accepted=True,
    )

    assert store.has_prompted_group(987654321)
    assert store.get_pending_prompt(987654321) is None
