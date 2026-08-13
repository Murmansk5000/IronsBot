from __future__ import annotations

from dataclasses import dataclass

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.runtime.in_flight_requests import InFlightRequestService

USER_ID = 100
OTHER_USER_ID = 200
ACTOR = ActorRef(Platform.ONEBOT, str(USER_ID))
OTHER_ACTOR = ActorRef(Platform.ONEBOT, str(OTHER_USER_ID))
DUPLICATE_MESSAGE = "重复请求"


def _request(action_id: str, target_key: str) -> SemanticRequest:
    return SemanticRequest(
        action=ActionDefinition(action_id, action_id),
        target=SemanticTarget(target_key, target_key),
        source=SemanticRequestSource.DIRECT,
    )


def _service(features: _Features | None = None) -> InFlightRequestService:
    return InFlightRequestService(
        features or _Features(),
        CommandCooldownConfig(
            duplicate_window_seconds=60,
            duplicate_message=DUPLICATE_MESSAGE,
        ),
    )


@dataclass
class _Features:
    superusers: frozenset[ActorRef] = frozenset()

    def is_actor_superuser(self, actor: ActorRef) -> bool:
        return actor in self.superusers


def test_in_flight_request_replies_once_warns_once_then_stays_silent() -> None:
    service = _service()

    first = service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=0,
    )
    second = service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=1,
    )

    assert first.allowed
    assert first.token is not None
    assert not second.allowed
    assert second.feedback == DUPLICATE_MESSAGE

    assert not service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=2,
    ).allowed

    service.finish(first.token, now=5)

    completed_duplicate = service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=64,
    )
    assert not completed_duplicate.allowed
    assert completed_duplicate.feedback is None

    assert not service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=64.5,
    ).allowed

    assert service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=65,
    ).allowed


def test_in_flight_request_release_does_not_create_a_recent_response() -> None:
    service = _service()
    first = service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=0,
    )
    assert first.token is not None

    service.release(first.token)

    assert service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
        now=1,
    ).allowed


def test_in_flight_request_keeps_actors_actions_and_targets_independent() -> None:
    service = _service()

    first = service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
    )
    assert first.allowed
    assert service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5001"),
    ).allowed
    assert service.admit(
        actor=ACTOR,
        request=_request("seer_pet_image", "5000"),
    ).allowed
    assert service.admit(
        actor=OTHER_ACTOR,
        request=_request("seer_pet_info", "5000"),
    ).allowed


def test_in_flight_request_keeps_platform_actor_namespaces_isolated() -> None:
    service = _service()
    official_actor = ActorRef(Platform.QQ_OFFICIAL, str(USER_ID))

    assert service.admit(
        actor=ACTOR,
        request=_request("seer_pet_info", "5000"),
    ).allowed
    assert service.admit(
        actor=official_actor,
        request=_request("seer_pet_info", "5000"),
    ).allowed


def test_in_flight_request_superusers_bypass_reservations() -> None:
    service = _service(_Features(frozenset({ACTOR})))

    first = service.admit(
        actor=ACTOR,
        request=_request("seer.player.collection", "712345678"),
    )
    second = service.admit(
        actor=ACTOR,
        request=_request("seer.player.collection", "712345678"),
    )

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_in_flight_request_stale_token_does_not_release_new_reservation() -> None:
    service = _service()
    first = service.admit(
        actor=ACTOR,
        request=_request("seer_mintmark_query", "45001"),
    )
    assert first.token is not None
    service.finish(first.token, now=0)
    second = service.admit(
        actor=ACTOR,
        request=_request("seer_mintmark_query", "45001"),
        now=60,
    )
    assert second.token is not None

    service.finish(first.token)

    assert not service.admit(
        actor=ACTOR,
        request=_request("seer_mintmark_query", "45001"),
    ).allowed
