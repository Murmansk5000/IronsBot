# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.type_matchup_repository import (
    load_type_matchup_dataset,
    resolve_type_combinations,
)
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.type_calc import (
    MissingTypeRelationError,
    TypeCombinationSnapshot,
    TypeMatchup,
    custom_type_matchup,
    type_matchup_by_id,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.render_cache import RenderCache

TypeMatchupRenderer = Callable[[TypeMatchup], Awaitable[bytes]]


@dataclass(frozen=True, slots=True)
class TypeRenderSession:
    data: SeerDataReader
    render: TypeMatchupRenderer
    cache: RenderCache


TypeRenderSessionFactory = Callable[[], AbstractContextManager[TypeRenderSession]]
PROMPT_MAX_ITEMS = 20
NORMAL_TYPE_ID = 8
NORMAL_TYPE_MESSAGE = "普通系不支持属性克制表查询，李在赣神魔"
INCOMPLETE_TYPE_DATA_MESSAGE = "❌ 属性克制数据不完整，暂时无法生成结果。"
logger = logging.getLogger(__name__)


class TypeQueryService:
    def __init__(self, render_session: TypeRenderSessionFactory) -> None:
        self._render_session = render_session

    async def search(self, arg: str) -> QueryResult[int]:
        return await self._request(None, arg=arg)

    async def select(self, type_id: int) -> QueryResult[int]:
        return await self._request(type_id)

    async def _request(self, type_id: int | None, *, arg: str = "") -> QueryResult[int]:
        with self._render_session() as inputs:
            # Exact text preserves resolver semantics and DIY presentation order.
            key = render_request_cache_key("type_matchup", ("query-v1", type_id, arg))
            entry = inputs.cache.entry("type_matchup", key)
            if image := entry.get():
                return QueryResult(reply=QueryReply(image=image))
            result = await self._uncached(inputs, type_id, arg=arg)
            if result.reply is not None and result.reply.image:
                entry.put(result.reply.image)
            return result

    async def _uncached(
        self, inputs: TypeRenderSession, type_id: int | None, *, arg: str
    ) -> QueryResult[int]:
        missing_message = (
            f"❌未找到属性 {type_id}（这是一个bug，请反馈给开发者）"
            if type_id is not None
            else ""
        )
        if type_id is None:
            with inputs.data.query(
                partial(resolve_type_combinations, arg=arg)
            ) as combinations:
                if len(combinations) > PROMPT_MAX_ITEMS:
                    return QueryResult(
                        message=f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！"
                    )
                if len(combinations) > 1:
                    return QueryResult(
                        choices=tuple(
                            QueryChoice(item.name, str(item.id), item.id)
                            for item in combinations
                        )
                    )
                if combinations:
                    target = combinations[0]
                    if _contains_normal_type(target):
                        return QueryResult(message=NORMAL_TYPE_MESSAGE)
                    type_id = target.id
        with inputs.data.query(load_type_matchup_dataset) as dataset:
            try:
                matchup = (
                    custom_type_matchup(dataset, arg=arg)
                    if type_id is None
                    else type_matchup_by_id(dataset, type_id=type_id)
                )
            except MissingTypeRelationError as error:
                logger.exception(
                    "type matchup data is incomplete: attacker_id=%s defender_id=%s",
                    error.attacker_id,
                    error.defender_id,
                )
                matchup = None
                missing_message = INCOMPLETE_TYPE_DATA_MESSAGE
        if matchup is None:
            return QueryResult(message=missing_message)
        if _contains_normal_type(matchup.target):
            return QueryResult(message=NORMAL_TYPE_MESSAGE)
        return QueryResult(reply=QueryReply(image=await inputs.render(matchup)))


def _contains_normal_type(type_combination: TypeCombinationSnapshot) -> bool:
    return NORMAL_TYPE_ID in {
        type_combination.primary_id,
        type_combination.secondary_id,
    }
