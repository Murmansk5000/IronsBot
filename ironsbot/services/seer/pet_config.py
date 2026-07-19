# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ironsbot.services.seer.query_result import (
    QueryChoice,
    QueryReply,
    QueryResult,
)

if TYPE_CHECKING:
    from seerapi_models import PetORM

    from ironsbot.services.seer.data import SeerDataAccess


PET_CONFIG_PROMPT_MAX_ITEMS = 20


class PetConfigImageStore(Protocol):
    async def load(self, pet_id: int) -> bytes | None: ...


class PetConfigQueryService:
    """Resolve pets normally, then serve their locally maintained config art."""

    def __init__(
        self,
        data: SeerDataAccess,
        images: PetConfigImageStore,
    ) -> None:
        self._data = data
        self._images = images

    async def search(self, arg: str) -> QueryResult[int]:
        query = arg.strip()
        if not query:
            return QueryResult()

        with self._data.resolve(self._data.pet, query) as values:
            pets = tuple(values)
        if not pets:
            return QueryResult()
        if len(pets) == 1:
            return QueryResult(reply=await self._reply_for_pet(pets[0]))
        if len(pets) > PET_CONFIG_PROMPT_MAX_ITEMS:
            exact = next(
                (
                    pet
                    for pet in pets
                    if len(query) == 1 and pet.name == query
                ),
                None,
            )
            if exact is not None:
                return QueryResult(reply=await self._reply_for_pet(exact))
            return QueryResult(
                message=(
                    f"重名超过{PET_CONFIG_PROMPT_MAX_ITEMS}个，请重新检索关键词："
                )
            )

        return QueryResult(
            choices=tuple(
                QueryChoice(str(pet.name), str(pet.id), int(pet.id))
                for pet in pets
            )
        )

    async def select(self, pet_id: int) -> QueryResult[object]:
        with self._data.get(self._data.pet, pet_id) as pet:
            if pet is None:
                return QueryResult(
                    message=(
                        f"❌未找到精灵 {pet_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
        return QueryResult(reply=await self._reply_for_pet(pet))

    async def _reply_for_pet(self, pet: PetORM) -> QueryReply:
        image = await self._images.load(int(pet.id))
        if image is None:
            return QueryReply(
                text=f"❌暂未收录精灵 {pet.name}（{pet.id}）的配置图。"
            )
        return QueryReply(
            leading_text=f"🧩【{pet.name}配置】\n",
            image=image,
        )
