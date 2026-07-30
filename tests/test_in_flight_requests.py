from __future__ import annotations

from dataclasses import dataclass

from ironsbot.runtime.in_flight_requests import (
    DUPLICATE_REQUEST_MESSAGE,
    InFlightRequestService,
)
from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)

USER_ID = 100
OTHER_USER_ID = 200


def _request(action_id: str, target_key: str) -> SemanticRequest:
    return SemanticRequest(
        action=ActionDefinition(action_id, action_id),
        target=SemanticTarget(target_key, target_key),
        source=SemanticRequestSource.DIRECT,
    )


@dataclass
class _Features:
    superusers: frozenset[int] = frozenset()

    def is_superuser(self, user_id: int) -> bool:
        return user_id in self.superusers


def test_in_flight_request_replies_once_warns_once_then_stays_silent(
) -> None:
    service = InFlightRequestService(_Features())

    first = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=0,
    )
    second = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=1,
    )

    assert first.allowed
    assert first.token is not None
    assert not second.allowed
    assert second.feedback == DUPLICATE_REQUEST_MESSAGE

    assert not service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=2,
    ).allowed

    service.finish(first.token, now=5)

    completed_duplicate = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=64,
    )
    assert not completed_duplicate.allowed
    assert completed_duplicate.feedback == DUPLICATE_REQUEST_MESSAGE

    assert not service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=64.5,
    ).allowed

    assert service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=65,
    ).allowed


def test_in_flight_request_release_does_not_create_a_recent_response() -> None:
    service = InFlightRequestService(_Features())
    first = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=0,
    )
    assert first.token is not None

    service.release(first.token)

    assert service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=1,
    ).allowed


def test_in_flight_request_keeps_users_actions_and_targets_independent() -> None:
    service = InFlightRequestService(_Features())

    first = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
    )
    assert first.allowed
    assert service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5001"),
    ).allowed
    assert service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_image", "5000"),
    ).allowed
    assert service.admit(
        user_id=OTHER_USER_ID,
        request=_request("seer_pet_info", "5000"),
    ).allowed


def test_in_flight_request_superusers_bypass_reservations() -> None:
    service = InFlightRequestService(_Features(frozenset({USER_ID})))

    first = service.admit(
        user_id=USER_ID,
        request=_request("seer.player.collection", "105023264"),
    )
    second = service.admit(
        user_id=USER_ID,
        request=_request("seer.player.collection", "105023264"),
    )

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_in_flight_request_stale_token_does_not_release_new_reservation() -> None:
    service = InFlightRequestService(_Features())
    first = service.admit(
        user_id=USER_ID,
        request=_request("seer_mintmark_query", "45001"),
    )
    assert first.token is not None
    service.finish(first.token, now=0)
    second = service.admit(
        user_id=USER_ID,
        request=_request("seer_mintmark_query", "45001"),
        now=60,
    )
    assert second.token is not None

    service.finish(first.token)

    assert not service.admit(
        user_id=USER_ID,
        request=_request("seer_mintmark_query", "45001"),
    ).allowed
