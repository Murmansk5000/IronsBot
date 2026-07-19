from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.pet_config import PetConfigQueryService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess


class FakeData:
    pet = object()

    def __init__(self) -> None:
        self.pets: tuple[Any, ...] = ()
        self.resolve_args: list[str] = []

    @contextmanager
    def resolve(
        self,
        _getter: object,
        arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        self.resolve_args.append(arg)
        yield self.pets

    @contextmanager
    def get(
        self,
        _getter: object,
        pet_id: int,
    ) -> Iterator[Any | None]:
        yield next((pet for pet in self.pets if pet.id == pet_id), None)


class FakeImages:
    def __init__(self, images: dict[int, bytes] | None = None) -> None:
        self.images = images or {}
        self.requested_ids: list[int] = []

    async def load(self, pet_id: int) -> bytes | None:
        self.requested_ids.append(pet_id)
        return self.images.get(pet_id)


def _pet(pet_id: int, name: str) -> Any:
    return SimpleNamespace(id=pet_id, name=name)


def _service(data: FakeData, images: FakeImages) -> PetConfigQueryService:
    return PetConfigQueryService(cast("SeerDataAccess", data), images)


@pytest.mark.asyncio
async def test_pet_config_query_uses_normal_pet_resolution() -> None:
    data = FakeData()
    data.pets = (_pet(4923, "莫缇"),)
    images = FakeImages({4923: b"config"})

    result = await _service(data, images).search("天堂龙")

    assert data.resolve_args == ["天堂龙"]
    assert images.requested_ids == [4923]
    assert result.reply is not None
    assert result.reply.leading_text == "🧩【莫缇配置】\n"
    assert result.reply.image == b"config"


@pytest.mark.asyncio
async def test_known_pet_without_local_config_reports_missing_image() -> None:
    data = FakeData()
    data.pets = (_pet(4923, "莫缇"),)

    result = await _service(data, FakeImages()).search("莫缇")

    assert result.reply is not None
    assert result.reply.text == "❌暂未收录精灵 莫缇（4923）的配置图。"


@pytest.mark.asyncio
async def test_pet_config_query_prompts_then_selects_pet() -> None:
    data = FakeData()
    data.pets = (_pet(1, "雷伊"), _pet(2, "雷伊·完全体"))
    images = FakeImages({2: b"config"})
    service = _service(data, images)

    result = await service.search("雷伊")

    assert [(choice.name, choice.value) for choice in result.choices] == [
        ("雷伊", 1),
        ("雷伊·完全体", 2),
    ]
    selected = await service.select(2)
    assert selected.reply is not None
    assert selected.reply.image == b"config"


@pytest.mark.asyncio
async def test_pet_config_query_ignores_unknown_pet() -> None:
    result = await _service(FakeData(), FakeImages()).search("不存在的精灵")

    assert result.reply is None
    assert result.choices == ()
    assert result.message == ""
