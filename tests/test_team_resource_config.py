from pathlib import Path
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.integrations.storage.team_resources import (
    TeamResourceSubscriptionStore,
)
from ironsbot.services.team.resource import (
    TeamResourceService,
    TeamResourceSubscriptionUpdate,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService

TEAM_ID = 1234567
TEAM_RESOURCE_THRESHOLD = 2000
OWNER_ID = 1234567890
ADMIN_ID = 2345678901
UNUSED_HEADLESS = cast("HeadlessService", object())


def _service(
    config: TeamResourceConfig,
    aliases: dict[str, int],
) -> tuple[TeamResourceService, TeamResourceSubscriptionStore]:
    runtime = build_test_runtime()
    store = TeamResourceSubscriptionStore(config.subscription_path)
    return (
        TeamResourceService(
            config,
            store,
            UNUSED_HEADLESS,
            aliases,
            runtime.features,
            runtime.delivery,
        ),
        store,
    )


def test_team_resource_subscription_store_is_used_for_group(
    tmp_path: Path,
) -> None:
    config = TeamResourceConfig(
        subscription_path=tmp_path / "team_resource.sqlite",
        default_at_users=["owner", "2345678901"],
    )
    service, store = _service(config, {"owner": OWNER_ID})

    store.upsert(
        TeamResourceSubscriptionUpdate(
            group_id=987654321,
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
            at_user_ids=(OWNER_ID, ADMIN_ID),
            operator_id=OWNER_ID,
        )
    )

    subscriptions = store.list_group(987654321)

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
    service, store = _service(config, {})

    assert not service.enabled
    assert store.list_all() == []


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
