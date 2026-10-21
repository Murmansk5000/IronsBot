# SPDX-License-Identifier: MIT
"""Shared pet-flip game over structured members and detached published facts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from anyio import to_thread

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    TextPart,
)
from ironsbot.services.seer.images import fetch_optional_image
from ironsbot.services.seer.type_calc import (
    TypeCombinationSnapshot,
    TypeMatchupDataset,
    build_type_matchup,
)

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import MessagePart
    from ironsbot.services.seer.images import SeerImageSource

_PLAYER_COUNT = 2


@dataclass(frozen=True, slots=True)
class FlipPet:
    id: int
    name: str
    resource_id: int
    element: TypeCombinationSnapshot


class PetFlipRepository(Protocol):
    def draw(self) -> tuple[tuple[FlipPet, ...], TypeMatchupDataset]: ...


class PetFlipService:
    def __init__(self, repository: PetFlipRepository, images: SeerImageSource) -> None:
        self._repository = repository
        self._images = images

    async def play(self, text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        members = tuple(
            dict.fromkeys(
                actor for actor in context.member_mentions if actor.id != "all"
            )
        )
        if len(members) != _PLAYER_COUNT:
            return OutboundMessage.from_text(
                "请@两名不同成员后再抛精灵，例如：抛精灵 @张三 @李四"
            )
        pets, dataset = await to_thread.run_sync(self._repository.draw)
        if len(pets) != _PLAYER_COUNT or pets[0].id == pets[1].id:
            return OutboundMessage.from_text(
                "精灵数据库暂时没有足够的不同精灵，请稍后再试。"
            )
        first, second = pets
        forward = next(
            value
            for target, value in build_type_matchup(
                dataset, target=first.element
            ).attack_table
            if target.id == second.element.id
        )
        reverse = next(
            value
            for target, value in build_type_matchup(
                dataset, target=second.element
            ).attack_table
            if target.id == first.element.id
        )
        winner = 0 if (forward, first.id) > (reverse, second.id) else 1
        avatars = await asyncio.gather(
            *(
                fetch_optional_image(self._images, "pet_head", str(pet.resource_id))
                for pet in pets
            )
        )
        parts: list[MessagePart] = [TextPart("抛精灵！\n")]
        for member, pet, avatar in zip(members, pets, avatars, strict=True):
            parts.extend(
                (
                    MentionPart(member),
                    TextPart(
                        f" 召唤了【{pet.name}】（{pet.element.name} · ID: {pet.id}）\n"
                    ),
                )
            )
            if avatar.data:
                parts.append(BinaryImagePart(avatar.data, "image/png"))
        tie = "，序号大者胜" if forward == reverse else ""
        parts.extend(
            (
                TextPart(f"克制系数 {forward:g} : {reverse:g}{tie} —— "),
                MentionPart(members[winner]),
                TextPart(" 获胜！"),
            )
        )
        return OutboundMessage(tuple(parts))
