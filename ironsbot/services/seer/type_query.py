# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.type_matchup_repository import (
    load_type_matchup_dataset,
)
from ironsbot.services.seer.query_result import (
    QueryChoice,
    QueryReply,
    QueryResult,
)
from ironsbot.services.seer.type_calc import (
    TypeCombinationSnapshot,
    TypeMatchup,
    custom_type_matchup,
    type_matchup_by_id,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess

TypeMatchupRenderer = Callable[[TypeMatchup], Awaitable[bytes]]
PROMPT_MAX_ITEMS = 20
NORMAL_TYPE_ID = 8
NORMAL_TYPE_MESSAGE = "普通系不支持属性克制表查询，李在赣神魔"


class TypeQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        render: TypeMatchupRenderer,
    ) -> None:
        self._data = data
        self._render = render

    async def search(self, arg: str) -> QueryResult[int]:
        with self._data.resolve(self._data.type_combination, arg) as values:
            combinations = tuple(values)
            if not combinations:
                target_id = None
            elif len(combinations) == 1:
                target = combinations[0]
                if _contains_normal_type(target):
                    return QueryResult(message=NORMAL_TYPE_MESSAGE)
                target_id = int(target.id)
            elif len(combinations) > PROMPT_MAX_ITEMS:
                return QueryResult(
                    message=f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！"
                )
            else:
                return QueryResult(
                    choices=tuple(
                        QueryChoice(str(item.name), str(item.id), int(item.id))
                        for item in combinations
                    )
                )
        if target_id is None:
            with self._data.query(load_type_matchup_dataset) as dataset:
                resolved_matchup = custom_type_matchup(dataset, arg=arg)
            return (
                QueryResult()
                if resolved_matchup is None
                else await self._render_matchup(resolved_matchup)
            )
        with self._data.query(load_type_matchup_dataset) as dataset:
            resolved_matchup = type_matchup_by_id(dataset, type_id=target_id)
        return (
            QueryResult()
            if resolved_matchup is None
            else await self._render_matchup(resolved_matchup)
        )

    async def select(self, type_id: int) -> QueryResult[int]:
        with self._data.query(load_type_matchup_dataset) as dataset:
            matchup = type_matchup_by_id(dataset, type_id=type_id)
            if matchup is None:
                return QueryResult(
                    message=(
                        f"❌未找到属性 {type_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            resolved_matchup = matchup
        return await self._render_matchup(resolved_matchup)

    async def _render_matchup(self, matchup: TypeMatchup) -> QueryResult[int]:
        if _contains_normal_type(matchup.target):
            return QueryResult(message=NORMAL_TYPE_MESSAGE)
        return QueryResult(
            reply=QueryReply(image=await self._render(matchup))
        )


def _contains_normal_type(
    type_combination: TypeCombinationSnapshot,
) -> bool:
    return NORMAL_TYPE_ID in {
        type_combination.primary_id,
        type_combination.secondary_id,
    }
