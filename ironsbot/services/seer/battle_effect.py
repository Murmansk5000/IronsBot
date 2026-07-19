# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import fetch_optional_image
from ironsbot.services.seer.query_result import (
    QueryChoice,
    QueryReply,
    QueryResult,
)

if TYPE_CHECKING:
    from seerapi_models import BattleEffectORM

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource

PROMPT_MAX_ITEMS = 20


@dataclass(frozen=True, slots=True)
class _BattleEffectReplyData:
    effect_id: int
    text: str


class BattleEffectQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        images: SeerImageSource,
    ) -> None:
        self._data = data
        self._images = images

    async def search(self, arg: str) -> QueryResult[int]:
        with self._data.resolve(self._data.battle_effect, arg) as values:
            effects = tuple(values)
            if not effects:
                return QueryResult()
            if len(effects) == 1:
                reply_data = self._reply_data(effects[0])
            elif len(effects) > PROMPT_MAX_ITEMS:
                return QueryResult(
                    message=f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！"
                )
            else:
                return QueryResult(
                    choices=tuple(
                        QueryChoice(
                            str(effect.name),
                            str(effect.id),
                            int(effect.id),
                        )
                        for effect in effects
                    )
                )
        return QueryResult(reply=await self._build_reply(reply_data))

    async def select(self, effect_id: int) -> QueryResult[int]:
        with self._data.get(self._data.battle_effect, effect_id) as effect:
            if effect is None:
                return QueryResult(
                    message=(
                        f"❌未找到异常状态 {effect_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            reply_data = self._reply_data(effect)
        return QueryResult(reply=await self._build_reply(reply_data))

    @staticmethod
    def _reply_data(effect: BattleEffectORM) -> _BattleEffectReplyData:
        resistance_name = effect.resistance.name if effect.resistance else "无"
        return _BattleEffectReplyData(
            effect_id=int(effect.id),
            text=(
                f"【{effect.name}（ID：{effect.id}）】\n"
                f"类型：{'，'.join(item.name for item in effect.type) or '无'}\n"
                f"抗性类型：{resistance_name}\n"
                f"效果：{effect.desc}"
            ),
        )

    async def _build_reply(
        self,
        reply_data: _BattleEffectReplyData,
    ) -> QueryReply:
        image = await fetch_optional_image(
            self._images,
            "battle_effect",
            str(reply_data.effect_id),
        )
        return QueryReply(
            text=reply_data.text,
            image=image.data,
            image_error=image.error,
        )
