from __future__ import annotations

from typing import Any, cast

from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.runtime.prompts import Prompt, PromptItem, _prompt_semantic_request
from ironsbot.runtime.semantic_requests import ActionDefinition, SemanticTarget
from tests.helpers.onebot_events import group_message_event


def test_prompt_identity_uses_the_selected_stable_target() -> None:
    prompt = Prompt(
        title="选择精灵",
        action=ActionDefinition("seer_pet_info", "精灵信息查询"),
        items=[
            PromptItem(
                "谱尼", "5000", 5000, semantic_target=SemanticTarget("5000", "谱尼")
            ),
            PromptItem(
                "索伦森", "3032", 3032, semantic_target=SemanticTarget("3032", "索伦森")
            ),
        ],
    )

    first = _prompt_semantic_request(
        group_message_event("1"),
        cast("Any", {"prompt": prompt}),
    )
    second = _prompt_semantic_request(
        group_message_event("2"),
        cast("Any", {"prompt": prompt}),
    )

    assert first is not None
    assert second is not None
    assert (first.action.id, first.target.key) == ("seer_pet_info", "5000")
    assert (second.action.id, second.target.key) == ("seer_pet_info", "3032")


def test_prompt_reservation_keeps_1_then_2_and_drops_repeated_1() -> None:
    class Features:
        def is_superuser(self, user_id: int) -> bool:
            del user_id
            return False

    prompt = Prompt(
        title="选择精灵",
        action=ActionDefinition("seer_pet_info", "精灵信息查询"),
        items=[
            PromptItem(
                "谱尼", "5000", 5000, semantic_target=SemanticTarget("5000", "谱尼")
            ),
            PromptItem(
                "索伦森", "3032", 3032, semantic_target=SemanticTarget("3032", "索伦森")
            ),
        ],
    )
    service = InFlightRequestService(Features())
    state = cast("Any", {"prompt": prompt})

    first_identity = _prompt_semantic_request(group_message_event("1"), state)
    second_identity = _prompt_semantic_request(group_message_event("2"), state)
    repeated_identity = _prompt_semantic_request(group_message_event("1"), state)
    assert first_identity is not None
    assert second_identity is not None
    assert repeated_identity is not None

    first = service.admit(
        user_id=1,
        request=first_identity,
    )
    second = service.admit(
        user_id=1,
        request=second_identity,
    )
    repeated = service.admit(
        user_id=1,
        request=repeated_identity,
    )

    assert first.allowed
    assert second.allowed
    assert not repeated.allowed
    assert repeated.feedback is not None
