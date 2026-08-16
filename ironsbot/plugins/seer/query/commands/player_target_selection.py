# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared numbered selection menu for ambiguous configured player aliases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ironsbot.runtime.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.runtime.semantic_requests import ActionDefinition, SemanticTarget

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.typing import T_State

    from .player_target import PlayerTargetResolution

PlayerTargetSelectionCallback = Callable[
    [int, Matcher, MessageEvent],
    Awaitable[None],
]

_PLAYER_TARGET_SELECTION_ACTION = ActionDefinition(
    "seer_player_target_selection",
    "选择玩家",
)


async def enter_player_target_selection(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    target: PlayerTargetResolution,
    select_target: PlayerTargetSelectionCallback,
) -> None:
    """Present visible partial matches and continue through the caller's flow."""

    async def select(
        item: PromptItem[int],
        selection_matcher: Matcher,
        selection_event: Event,
    ) -> None:
        if isinstance(selection_event, MessageEvent):
            await select_target(item.value, selection_matcher, selection_event)

    await enter_prompt(
        matcher,
        event,
        state,
        Prompt(
            title="请问你想查询哪位玩家？",
            action=_PLAYER_TARGET_SELECTION_ACTION,
            items=[
                PromptItem(
                    choice.label,
                    f"游戏内ID：{choice.player_id}",
                    choice.player_id,
                    semantic_target=SemanticTarget(
                        key=str(choice.player_id),
                        display=choice.label,
                    ),
                )
                for choice in target.choices
            ],
        ),
        select,
    )
