from __future__ import annotations

from unittest.mock import AsyncMock

from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
)
from ironsbot.services.seer.player_query import (
    PLAYER_AUTOCARD_KEY,
    PLAYER_COLLECTION_KEY,
    PLAYER_PEAK_KEY,
    PlayerDetailPromptPlan,
    PlayerQuerySectionPlan,
    extract_player_query_arg,
    plan_player_detail_prompt,
    plan_player_query_sections,
    resolve_player_detail_reply,
)
from ironsbot.services.seer.query_result import QueryReply


def test_extract_player_query_arg_accepts_explicit_and_default_forms() -> None:
    assert extract_player_query_arg("米米号123456") == "123456"
    assert extract_player_query_arg("米米号") == ""
    assert extract_player_query_arg("not a player command") is None


def test_player_detail_resolver_accepts_only_current_menu_numbers() -> None:
    selections = (
        ("1", PLAYER_COLLECTION_KEY),
        ("2", PLAYER_PEAK_KEY),
        ("3", PLAYER_AUTOCARD_KEY),
    )

    collection = resolve_player_detail_reply("1", selections=selections)
    peak = resolve_player_detail_reply("2", selections=selections)

    assert collection is not None
    assert collection.key == PLAYER_COLLECTION_KEY
    assert peak is not None
    assert peak.key == PLAYER_PEAK_KEY
    assert resolve_player_detail_reply("收集", selections=selections) is None
    assert resolve_player_detail_reply("巅峰", selections=selections) is None
    assert resolve_player_detail_reply("阵容", selections=selections) is None


def test_plan_player_query_sections_maps_configured_sections() -> None:
    plan = plan_player_query_sections(
        ("basic", "collection", "local_rank", "peak", "autocard"),
        local_rank_enabled=True,
    )

    assert plan == PlayerQuerySectionPlan(
        show_local_rank=True,
        has_collection=True,
        needs_peak_section=True,
        has_autocard_rank=True,
        needs_online_info=True,
        local_rank_enabled=True,
    )


def test_player_detail_prompt_assigns_standard_menu_numbers_in_registration_order(
) -> None:
    extension = PlayerDetailExtensionAction(
        id="private_action",
        feature="private_feature",
        label="private action",
        aliases=("private",),
        query=AsyncMock(return_value=QueryReply(text="ok")),
    )

    plan = plan_player_detail_prompt(
        has_collection=True,
        has_peak=True,
        has_autocard=True,
        supports_conversation=True,
        extension_actions=(extension,),
    )

    assert plan == PlayerDetailPromptPlan(
        accepted_commands=(
            "1",
            "2",
            "3",
            "4",
            "0",
        ),
        prompt_lines=(
            "回复数字查看详情：",
            "1.【收集】",
            "2.【巅峰】",
            "3.【群星牌】",
            "4.【private action】",
            "0.【退出】",
        ),
        builtin_selections=(
            ("1", PLAYER_COLLECTION_KEY),
            ("2", PLAYER_PEAK_KEY),
            ("3", PLAYER_AUTOCARD_KEY),
        ),
        extension_selections=(("4", "private_action"),),
        should_enter_conversation=True,
    )


def test_player_detail_prompt_uses_registered_extension_actions() -> None:
    extension = PlayerDetailExtensionAction(
        id="private_action",
        feature="private_feature",
        label="private action",
        aliases=("private",),
        query=AsyncMock(return_value=QueryReply(text="ok")),
    )

    plan = plan_player_detail_prompt(
        has_collection=False,
        has_peak=True,
        has_autocard=False,
        supports_conversation=True,
        extension_actions=(extension,),
    )

    assert plan == PlayerDetailPromptPlan(
        accepted_commands=("1", "2", "0"),
        prompt_lines=(
            "回复数字查看详情：",
            "1.【巅峰】",
            "2.【private action】",
            "0.【退出】",
        ),
        builtin_selections=(("1", PLAYER_PEAK_KEY),),
        extension_selections=(("2", "private_action"),),
        should_enter_conversation=True,
    )
