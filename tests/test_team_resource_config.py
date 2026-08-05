from pathlib import Path
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.team_resources import TeamResourceSubscriptionStore
from ironsbot.services.team.resource import (
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceService,
    TeamResourceSubscriptionTarget,
    TeamResourceSubscriptionUpdate,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService

TEAM_ID = 1234567
TEAM_RESOURCE_THRESHOLD = 2000
OWNER_ID = 1234567890
ADMIN_ID = 2345678901
GROUP_ID = 987654321
UNUSED_HEADLESS = cast("HeadlessService", object())


class NoopTeamResourceNoticeSender:
    async def send_low_resource_notice(
        self,
        target: TeamResourceSubscriptionTarget,
        message: str,
    ) -> bool:
        del target, message
        return True


def _actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _group(group_id: int = GROUP_ID) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _service(
    config: TeamResourceConfig,
    state_path: Path,
    *,
    default_mentions: tuple[ActorRef, ...] = (),
) -> tuple[TeamResourceService, TeamResourceSubscriptionStore]:
    runtime = build_test_runtime()
    store = TeamResourceSubscriptionStore(state_path)
    return (
        TeamResourceService(
            config,
            store,
            UNUSED_HEADLESS,
            runtime.features,
            NoopTeamResourceNoticeSender(),
            default_mentions,
        ),
        store,
    )


def test_team_resource_subscription_store_is_used_for_group(
    tmp_path: Path,
) -> None:
    service, store = _service(
        TeamResourceConfig(),
        tmp_path / "qq_state.sqlite",
        default_mentions=(_actor(OWNER_ID), _actor(ADMIN_ID)),
    )
    store.upsert(
        TeamResourceSubscriptionUpdate(
            conversation=_group(),
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
            mention_actors=(_actor(OWNER_ID), _actor(ADMIN_ID)),
            operator=_actor(OWNER_ID),
        )
    )

    subscriptions = store.list_conversation(_group())

    assert len(subscriptions) == 1
    assert subscriptions[0].team_id == TEAM_ID
    assert subscriptions[0].threshold == TEAM_RESOURCE_THRESHOLD
    assert subscriptions[0].mention_actors == (_actor(OWNER_ID), _actor(ADMIN_ID))
    assert service.default_mention_actors == (_actor(OWNER_ID), _actor(ADMIN_ID))


def test_team_resource_disabled_has_no_subscriptions(tmp_path: Path) -> None:
    service, store = _service(
        TeamResourceConfig(enabled=False),
        tmp_path / "qq_state.sqlite",
    )

    assert not service.enabled
    assert store.list_all() == []


def test_team_resource_subscription_store_keeps_private_subscriptions_separate(
    tmp_path: Path,
) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "team_resource.sqlite")
    store.upsert_private(
        TeamResourcePrivateSubscriptionUpdate(
            actor=_actor(OWNER_ID),
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
        )
    )

    subscriptions = store.list_actor(_actor(OWNER_ID))

    assert len(subscriptions) == 1
    assert subscriptions[0].team_id == TEAM_ID
    assert subscriptions[0].threshold == TEAM_RESOURCE_THRESHOLD
    assert store.list_conversation(_group()) == []


def test_team_resource_service_uses_one_target_interface_for_subscriptions(
    tmp_path: Path,
) -> None:
    service, store = _service(TeamResourceConfig(), tmp_path / "qq_state.sqlite")
    store.upsert(
        TeamResourceSubscriptionUpdate(
            conversation=_group(),
            team_id=TEAM_ID,
            team_name="群战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
            mention_actors=(_actor(OWNER_ID),),
            operator=_actor(OWNER_ID),
        )
    )
    store.upsert_private(
        TeamResourcePrivateSubscriptionUpdate(
            actor=_actor(OWNER_ID),
            team_id=TEAM_ID,
            team_name="私聊战队",
            threshold=TEAM_RESOURCE_THRESHOLD,
        )
    )

    group_message = service.subscriptions_message(
        TeamResourceSubscriptionTarget(_group())
    )
    private_message = service.subscriptions_message(
        TeamResourceSubscriptionTarget(_actor(OWNER_ID))
    )

    assert "群战队" in group_message
    assert "提醒 1234567890" in group_message
    assert "私聊战队" in private_message
    assert "提醒" not in private_message


def test_team_resource_store_tracks_conversation_prompt_once(tmp_path: Path) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "team_resource.sqlite")

    assert not store.has_prompted_conversation(_group())
    assert store.get_pending_prompt(_group()) is None

    store.mark_conversation_prompted(
        conversation=_group(),
        team_id=TEAM_ID,
        team_name="示例战队",
        prompted_by=_actor(OWNER_ID),
    )

    prompt = store.get_pending_prompt(_group())
    assert prompt is not None
    assert store.has_prompted_conversation(_group())
    assert prompt.team_id == TEAM_ID
    assert prompt.team_name == "示例战队"
    assert prompt.prompted_by == _actor(OWNER_ID)

    store.mark_conversation_prompted(
        conversation=_group(),
        team_id=7654321,
        team_name="另一个战队",
        prompted_by=_actor(ADMIN_ID),
    )
    assert store.get_pending_prompt(_group()) == prompt


def test_team_resource_prompt_can_be_marked_handled(tmp_path: Path) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "team_resource.sqlite")
    store.mark_conversation_prompted(
        conversation=_group(),
        team_id=TEAM_ID,
        team_name="示例战队",
        prompted_by=_actor(OWNER_ID),
    )

    store.mark_prompt_handled(
        conversation=_group(),
        handled_by=_actor(ADMIN_ID),
        accepted=True,
    )

    assert store.has_prompted_conversation(_group())
    assert store.get_pending_prompt(_group()) is None
