# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.type_matchup_repository import (
    load_type_matchup_dataset,
)
from ironsbot.services.seer.data import SeerDataReader
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
TypeRenderSessionFactory = Callable[
    [], AbstractContextManager[tuple[SeerDataReader, TypeMatchupRenderer]]
]
PROMPT_MAX_ITEMS = 20
NORMAL_TYPE_ID = 8
NORMAL_TYPE_MESSAGE = "普通系不支持属性克制表查询，李在赣神魔"


class TypeQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        render_session: TypeRenderSessionFactory,
    ) -> None:
        self._data = data
        self._render_session = render_session

    async def search(self, arg: str) -> QueryResult[int]:
        with self._data.resolve(self._data.type_combination, arg) as values:
            combinations = tuple(values)
            if not combinations:
                target_id = None
            elif len(combinations) == 1:
                target = combinations[0]
                if _contains_normal_type_ids(
                    int(target.primary_id),
                    None if target.secondary_id is None else int(target.secondary_id),
                ):
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
        return await self._render_request(target_id, arg=arg)

    async def select(self, type_id: int) -> QueryResult[int]:
        return await self._render_request(
            type_id,
            missing_message=f"❌未找到属性 {type_id}（这是一个bug，请反馈给开发者）",
        )

    async def _render_request(
        self, type_id: int | None, *, arg: str = "", missing_message: str = ""
    ) -> QueryResult[int]:
        with self._render_session() as (data, render):
            with data.query(load_type_matchup_dataset) as dataset:
                matchup = (
                    custom_type_matchup(dataset, arg=arg)
                    if type_id is None
                    else type_matchup_by_id(dataset, type_id=type_id)
                )
            if matchup is None:
                return QueryResult(message=missing_message)
            if _contains_normal_type(matchup.target):
                return QueryResult(message=NORMAL_TYPE_MESSAGE)
            return QueryResult(reply=QueryReply(image=await render(matchup)))


def _contains_normal_type(
    type_combination: TypeCombinationSnapshot,
) -> bool:
    return _contains_normal_type_ids(
        type_combination.primary_id,
        type_combination.secondary_id,
    )


def _contains_normal_type_ids(
    primary_id: int,
    secondary_id: int | None,
) -> bool:
    return NORMAL_TYPE_ID in {
        primary_id,
        secondary_id,
    }
