from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.runtime import prompts
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.runtime.prompts import Prompt, PromptItem, _prompt_semantic_request
from ironsbot.runtime.semantic_requests import ActionDefinition, SemanticTarget
from tests.helpers.onebot_events import group_message_event


def test_prompt_identity_uses_the_selected_stable_target() -> None:
    prompt = Prompt[Any](
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

    prompt = Prompt[Any](
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
    service = InFlightRequestService(Features(), CommandCooldownConfig())
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
    assert repeated.feedback == "该指令重复发送；后续重复不再提醒。"


def test_prompt_supports_explicit_letter_number_keys() -> None:
    prompt = Prompt[Any](
        title="新增内容",
        items=[
            PromptItem("新增精灵", "1 项", "category", key="a"),
            PromptItem("莫缇", "新增｜4923", 4923, is_sub_prompt=True, key="a1"),
        ],
    )

    request = _prompt_semantic_request(
        group_message_event("a1"),
        cast("Any", {"prompt": prompt}),
    )

    assert prompt.get_item_by_input("a1") is not None
    assert prompt.get_item_by_input("1") is None
    assert request is not None
    assert "a1. 莫缇" in prompt.build_message()


def test_hidden_explicit_prompt_item_remains_selectable() -> None:
    prompt = Prompt[Any](
        title="新增内容",
        items=[
            PromptItem("新增精灵", "1 项", "category", key="a"),
            PromptItem(
                "莫缇",
                "新增｜4923",
                4923,
                is_sub_prompt=True,
                key="a1",
                is_visible=False,
            ),
        ],
    )

    request = _prompt_semantic_request(
        group_message_event("a1"),
        cast("Any", {"prompt": prompt}),
    )

    assert prompt.get_item_by_input("a1") is not None
    assert request is not None
    assert "a1. 莫缇" not in prompt.build_message()


def test_hidden_prompt_items_require_unique_explicit_keys() -> None:
    with pytest.raises(ValueError, match="explicit keys"):
        Prompt[Any](
            title="新增内容",
            items=[
                PromptItem("新增精灵", "1 项", "category", key="a"),
                PromptItem("莫缇", "新增｜4923", 4923, is_visible=False),
            ],
        )


@pytest.mark.asyncio
async def test_async_prompt_message_reserves_input_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class PromptSessions:
        def acquire(self, session_id: str) -> int:
            assert session_id == "group_4_2"
            return 1

        def make_rule(
            self,
            session_id: str,
            version: int,
            input_check: object,
        ) -> object:
            del input_check
            assert (session_id, version) == ("group_4_2", 1)
            return object()

        def cancel_queued_conversation(self, state: dict[str, object]) -> None:
            del state

    async def reserve_input(
        matcher: object,
        handlers: list[object],
        **kwargs: object,
    ) -> None:
        del matcher, handlers, kwargs
        order.append("reserve")

    async def render_menu() -> str:
        assert order == ["reserve"]
        order.append("render")
        return "menu"

    async def activate_menu(
        matcher: object,
        handlers: list[object],
        rule: object,
        prompt: object,
        **kwargs: object,
    ) -> None:
        del matcher, handlers, rule, kwargs
        assert prompt == "menu"
        order.append("activate")

    async def resolve_selection(selection: object, matcher: object) -> None:
        del selection, matcher

    sessions = PromptSessions()

    def get_sessions(_matcher: object) -> PromptSessions:
        return sessions

    monkeypatch.setattr(prompts, "get_prompt_session_manager", get_sessions)
    monkeypatch.setattr(prompts, "begin_queued_conversation", reserve_input)
    monkeypatch.setattr(prompts, "_enter_prompt_loop", activate_menu)

    matcher = cast("Any", SimpleNamespace(state={}))
    await prompts.enter_prompt(
        matcher,
        group_message_event("新增内容", user_id=2, group_id=4),
        matcher.state,
        Prompt(title="新增内容", items=[PromptItem("新增精灵", "1 项", "pet")]),
        resolve_selection,
        prompt_message=render_menu(),
    )

    assert order == ["reserve", "render", "activate"]
