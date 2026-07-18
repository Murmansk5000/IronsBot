from pathlib import Path

from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.services.team_resource_subscriptions import (
    TeamResourceService,
    TeamResourceSubscriptionStore,
    TeamResourceSubscriptionUpdate,
)
from tests.helpers.runtime import build_test_runtime

TEAM_ID = 1234567
TEAM_RESOURCE_THRESHOLD = 2000
OWNER_ID = 1234567890
ADMIN_ID = 2345678901


def test_team_resource_subscription_store_is_used_for_group(
    tmp_path: Path,
) -> None:
    config = TeamResourceConfig(
        subscription_path=tmp_path / "team_resource.sqlite",
        default_at_users=["owner", "2345678901"],
    )
    runtime = build_test_runtime()
    service = TeamResourceService.build(
        config,
        {"owner": OWNER_ID},
        runtime.features,
        runtime.delivery,
    )

    service.store.upsert(
        TeamResourceSubscriptionUpdate(
            group_id=987654321,
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
            at_user_ids=(OWNER_ID, ADMIN_ID),
            operator_id=OWNER_ID,
        )
    )

    subscriptions = service.store.list_group(987654321)

    assert len(subscriptions) == 1
    assert subscriptions[0].team_id == TEAM_ID
    assert subscriptions[0].threshold == TEAM_RESOURCE_THRESHOLD
    assert subscriptions[0].at_user_ids == (OWNER_ID, ADMIN_ID)
    assert service.default_at_user_ids == (
        OWNER_ID,
        ADMIN_ID,
    )


def test_team_resource_disabled_has_no_subscriptions(
    tmp_path: Path,
) -> None:
    config = TeamResourceConfig(
        enabled=False,
        subscription_path=tmp_path / "team_resource.sqlite",
    )
    runtime = build_test_runtime()
    service = TeamResourceService.build(
        config,
        {},
        runtime.features,
        runtime.delivery,
    )

    assert not service.config.enabled
    assert service.store.list_all() == []


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
