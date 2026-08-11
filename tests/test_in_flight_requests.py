from __future__ import annotations

from dataclasses import dataclass

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.request_coordination import (
    RequestCoordinator,
    RequestDecisionKind,
)
from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)

USER_ID = 100
OTHER_USER_ID = 200
DUPLICATE_MESSAGE = "重复请求"


def _request(action_id: str, target_key: str) -> SemanticRequest:
    return SemanticRequest(
        action=ActionDefinition(action_id, action_id),
        target=SemanticTarget(target_key, target_key),
        source=SemanticRequestSource.DIRECT,
    )


def _service(features: _Features | None = None) -> RequestCoordinator:
    return RequestCoordinator(
        features or _Features(),
        CommandCooldownConfig(
            duplicate_window_seconds=60,
            duplicate_message=DUPLICATE_MESSAGE,
        ),
    )


@dataclass
class _Features:
    superusers: frozenset[int] = frozenset()

    def is_superuser(self, user_id: int) -> bool:
        return user_id in self.superusers


def test_in_flight_request_replies_once_warns_once_then_stays_silent(
) -> None:
    service = _service()

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
    assert first.kind is RequestDecisionKind.ADMITTED
    assert first.token is not None
    assert not second.allowed
    assert second.kind is RequestDecisionKind.DUPLICATE
    assert second.feedback == DUPLICATE_MESSAGE

    silent = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=2,
    )
    assert silent.kind is RequestDecisionKind.SILENT

    service.finish(first.token, now=5)

    completed_duplicate = service.admit(
        user_id=USER_ID,
        request=_request("seer_pet_info", "5000"),
        now=64,
    )
    assert not completed_duplicate.allowed
    assert completed_duplicate.feedback is None

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
    service = _service()
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
    service = _service()

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


def test_in_flight_request_keeps_the_same_user_independent_per_group() -> None:
    service = _service()
    request = _request("meeting_reply", "default")

    first = service.admit(
        user_id=USER_ID,
        request=request,
        scope="group:10001",
    )
    second_group = service.admit(
        user_id=USER_ID,
        request=request,
        scope="group:10002",
    )
    repeated_group = service.admit(
        user_id=USER_ID,
        request=request,
        scope="group:10001",
    )

    assert first.allowed
    assert second_group.allowed
    assert not repeated_group.allowed


def test_in_flight_request_superusers_bypass_reservations() -> None:
    service = _service(_Features(frozenset({USER_ID})))

    first = service.admit(
        user_id=USER_ID,
        request=_request("seer.player.collection", "712345678"),
    )
    second = service.admit(
        user_id=USER_ID,
        request=_request("seer.player.collection", "712345678"),
    )

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_in_flight_request_stale_token_does_not_release_new_reservation() -> None:
    service = _service()
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
