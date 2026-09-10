# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from seerapi_models import PetORM, PetSkinORM

from ironsbot.services.seer.images import fetch_optional_image
from ironsbot.services.seer.query_result import (
    QueryChoice,
    QueryReply,
    QueryResult,
)
from ironsbot.services.seer.skin_image_resolution import load_skin_image_resolutions
from ironsbot.services.seer.skin_price import load_skin_details

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource

logger = logging.getLogger(__name__)
PET_PROMPT_MAX_ITEMS = 20
PetInfoRenderer = Callable[[PetORM], Awaitable[bytes]]
PetRenderFailureNotifier = Callable[[str], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class PetImageSelection:
    resource_id: int
    name: str
    skin_id: int | None = None


class PetQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        images: SeerImageSource,
        render_info: PetInfoRenderer,
        render_failure_notifier: PetRenderFailureNotifier | None = None,
    ) -> None:
        self._data = data
        self._images = images
        self._render_info = render_info
        self._render_failure_notifier = render_failure_notifier

    async def search_image(
        self,
        arg: str,
    ) -> QueryResult[PetImageSelection]:
        with self._data.pet_and_skins(arg) as values:
            pets, skins = values
            choices = self._image_choices(pets, skins)
        if not arg.strip() or not choices:
            return QueryResult()
        if len(choices) == 1:
            return QueryResult(
                reply=await self._build_image_reply(
                    choices[0].value,
                )
            )
        if len(choices) > PET_PROMPT_MAX_ITEMS:
            exact = self._single_character_match(arg, choices)
            if exact is not None:
                return QueryResult(reply=await self._build_image_reply(exact.value))
            return QueryResult(
                message=(f"重名超过{PET_PROMPT_MAX_ITEMS}个，请重新检索关键词：")
            )
        return QueryResult(choices=choices)

    async def select_image(
        self,
        selection: PetImageSelection,
    ) -> QueryResult[object]:
        return QueryResult(reply=await self._build_image_reply(selection))

    async def search_info(self, arg: str) -> QueryResult[int]:
        return await self._search_pet(arg, self._build_info_reply)

    async def search_avatar(self, arg: str) -> QueryResult[int]:
        return await self._search_pet(arg, self._build_avatar_reply)

    async def _search_pet(
        self,
        arg: str,
        build_reply: Callable[[PetORM], Awaitable[QueryReply]],
    ) -> QueryResult[int]:
        with self._data.resolve(self._data.pet, arg) as values:
            pets = tuple(values)
            if not arg.strip() or not pets:
                return QueryResult()
            if len(pets) == 1:
                return QueryResult(reply=await build_reply(pets[0]))
            if len(pets) > PET_PROMPT_MAX_ITEMS:
                exact = next(
                    (pet for pet in pets if len(arg) == 1 and pet.name == arg),
                    None,
                )
                if exact is not None:
                    return QueryResult(reply=await build_reply(exact))
                return QueryResult(
                    message=(f"重名超过{PET_PROMPT_MAX_ITEMS}个，请重新检索关键词：")
                )
            return QueryResult(
                choices=tuple(
                    QueryChoice(str(pet.name), str(pet.id), int(pet.id)) for pet in pets
                )
            )

    async def select_info(self, pet_id: int) -> QueryResult[object]:
        with self._data.get(self._data.pet, pet_id) as pet:
            if pet is None:
                return QueryResult(
                    message=(f"❌未找到精灵 {pet_id}（这是一个bug，请反馈给开发者）")
                )
            return QueryResult(reply=await self._build_info_reply(pet))

    async def select_avatar(self, pet_id: int) -> QueryResult[object]:
        with self._data.get(self._data.pet, pet_id) as pet:
            if pet is None:
                return QueryResult(message=f"未找到精灵 {pet_id}。")
            return QueryResult(reply=await self._build_avatar_reply(pet))

    async def _build_avatar_reply(self, pet: PetORM) -> QueryReply:
        image = await fetch_optional_image(
            self._images, "pet_head", str(pet.resource_id)
        )
        return QueryReply(image=image.data, image_error=image.error)

    async def _build_image_reply(
        self,
        selection: PetImageSelection,
    ) -> QueryReply:
        body_resource_id = selection.resource_id
        if selection.skin_id is not None:
            with self._data.query(
                partial(
                    load_skin_image_resolutions,
                    skin_ids=(selection.skin_id,),
                )
            ) as resolutions:
                resolution = resolutions.get(selection.skin_id)
            if resolution is not None:
                body_resource_id = resolution.body_resource_id

        image_data: bytes | None = None
        image_error = ""
        if body_resource_id > 0:
            image = await fetch_optional_image(
                self._images,
                "pet_body",
                str(body_resource_id),
            )
            image_data = image.data
            image_error = image.error
        elif selection.skin_id is not None:
            image_error = "❌该经典皮肤的立绘资源未解析。"
        text = f"💎【{selection.name}】\n"
        with self._data.query(
            partial(load_skin_details, resource_id=selection.resource_id)
        ) as details:
            if details is not None:
                text += (
                    f"所属精灵：{details.pet_name}\n所属系列：{details.series_name}\n"
                )
                if details.card_price:
                    text += f"礼卡价格：{details.card_price}\n"
                text += details.price_lines
        return QueryReply(
            text=text,
            image=image_data,
            image_error=image_error,
        )

    async def _build_info_reply(self, pet: PetORM) -> QueryReply:
        pet_id = int(pet.id)
        pet_name = str(pet.name)
        resource_id = int(pet.resource_id)
        logger.info(
            "rendering pet info image: pet_id=%s pet_name=%s resource_id=%s",
            pet_id,
            pet_name,
            resource_id,
        )
        try:
            image = await self._render_info(pet)
        except Exception as error:
            logger.exception(
                "pet info render failed: pet_id=%s pet_name=%s resource_id=%s",
                pet_id,
                pet_name,
                resource_id,
            )
            await self._notify_render_failure(
                pet_id=pet_id,
                pet_name=pet_name,
                resource_id=resource_id,
                error=error,
            )
            raise
        logger.info(
            "rendered pet info image: pet_id=%s pet_name=%s bytes=%s",
            pet_id,
            pet_name,
            len(image),
        )
        return QueryReply(image=image)

    async def _notify_render_failure(
        self,
        *,
        pet_id: int,
        pet_name: str,
        resource_id: int,
        error: Exception,
    ) -> None:
        if self._render_failure_notifier is None:
            return
        message = (
            "⚠️ 精灵信息渲染失败。\n"
            f"精灵：{pet_name}\n"
            f"精灵ID：{pet_id}\n"
            f"资源ID：{resource_id}\n"
            f"异常类型：{type(error).__name__}"
        )
        try:
            await self._render_failure_notifier(message)
        except Exception:
            logger.exception(
                "pet render failure notice failed: pet_id=%s",
                pet_id,
            )

    @staticmethod
    def _image_choices(
        pets: Iterable[PetORM],
        skins: Iterable[PetSkinORM],
    ) -> tuple[QueryChoice[PetImageSelection], ...]:
        resource_ids: set[int] = set()
        choices: list[QueryChoice[PetImageSelection]] = []
        for pet in pets:
            if pet.id not in resource_ids:
                resource_ids.add(pet.id)
                choices.append(
                    QueryChoice(
                        pet.name,
                        str(pet.id),
                        PetImageSelection(pet.id, pet.name),
                    )
                )
            for skin in pet.skins:
                if skin.resource_id in resource_ids:
                    continue
                resource_ids.add(skin.resource_id)
                choices.append(
                    QueryChoice(
                        skin.name,
                        str(skin.resource_id),
                        PetImageSelection(
                            skin.resource_id,
                            skin.name,
                            int(getattr(skin, "id", 0) or 0) or None,
                        ),
                        is_sub_choice=True,
                    )
                )
        for skin in skins:
            if skin.resource_id in resource_ids:
                continue
            resource_ids.add(skin.resource_id)
            choices.append(
                QueryChoice(
                    skin.name,
                    f"所属精灵：{skin.pet.name}",
                    PetImageSelection(
                        skin.resource_id,
                        skin.name,
                        int(getattr(skin, "id", 0) or 0) or None,
                    ),
                )
            )
        return tuple(choices)

    @staticmethod
    def _single_character_match(
        arg: str,
        choices: Iterable[QueryChoice[PetImageSelection]],
    ) -> QueryChoice[PetImageSelection] | None:
        if len(arg) != 1:
            return None
        return next((choice for choice in choices if choice.name == arg), None)
