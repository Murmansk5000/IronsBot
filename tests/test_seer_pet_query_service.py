from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.pet_query import (
    PetImageSelection,
    PetQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from seerapi_models import PetORM

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource


class FakeData:
    pet = object()

    def __init__(self) -> None:
        self.pets: tuple[Any, ...] = ()
        self.skins: tuple[Any, ...] = ()
        self.skin_details: Any | None = None
        self.session_active = False

    @contextmanager
    def pet_and_skins(
        self,
        _arg: str,
    ) -> Iterator[tuple[tuple[Any, ...], tuple[Any, ...]]]:
        self.session_active = True
        try:
            yield self.pets, self.skins
        finally:
            self.session_active = False

    @contextmanager
    def resolve(
        self,
        _getter: object,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        self.session_active = True
        try:
            yield self.pets
        finally:
            self.session_active = False

    @contextmanager
    def get(
        self,
        _getter: object,
        pet_id: int,
    ) -> Iterator[Any | None]:
        self.session_active = True
        try:
            yield next((pet for pet in self.pets if pet.id == pet_id), None)
        finally:
            self.session_active = False

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any | None]:
        yield self.skin_details


class FakeImages:
    async def fetch(
        self,
        kind: object,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        assert kind == "pet_body"
        assert fallback is False
        return f"image:{key}".encode()


def _pet(pet_id: int, name: str) -> Any:
    return SimpleNamespace(
        id=pet_id,
        name=name,
        resource_id=pet_id,
        skins=[],
    )


class SessionBoundPet:
    def __init__(self, data: FakeData) -> None:
        self.id = 1
        self.name = "精灵"
        self.resource_id = 1
        self._data = data

    @property
    def base_stats(self) -> object:
        assert self._data.session_active
        return object()


class SessionBoundImagePet:
    id = 1
    name = "精灵"
    resource_id = 1

    def __init__(self, data: FakeData) -> None:
        self._data = data

    @property
    def skins(self) -> list[Any]:
        assert self._data.session_active
        return []


def _service(
    data: FakeData,
    rendered: list[Any] | None = None,
) -> PetQueryService:
    rendered = [] if rendered is None else rendered

    async def render(pet: PetORM) -> bytes:
        rendered.append(pet)
        return f"rendered:{pet.id}".encode()

    return PetQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages()),
        render,
    )


@pytest.mark.asyncio
async def test_pet_image_query_returns_deduplicated_choices() -> None:
    data = FakeData()
    pet = _pet(1, "精灵")
    skin = SimpleNamespace(
        name="皮肤",
        resource_id=101,
        pet=pet,
    )
    pet.skins = [skin]
    data.pets = (pet,)
    data.skins = (skin,)

    result = await _service(data).search_image("精")

    assert [
        (
            choice.name,
            choice.value.resource_id,
            choice.is_sub_choice,
        )
        for choice in result.choices
    ] == [
        ("精灵", 1, False),
        ("皮肤", 101, True),
    ]


@pytest.mark.asyncio
async def test_pet_image_choices_are_built_before_session_closes() -> None:
    data = FakeData()
    data.pets = (SessionBoundImagePet(data),)

    result = await _service(data).search_image("精灵")

    assert result.reply is not None
    assert result.reply.image == b"image:1"
    assert data.session_active is False


@pytest.mark.asyncio
async def test_pet_image_selection_includes_skin_details() -> None:
    data = FakeData()
    data.skin_details = SimpleNamespace(
        pet_name="精灵",
        series_name="周年",
        card_price=20,
        price_lines="售价：100",
    )

    result = await _service(data).select_image(
        PetImageSelection(101, "皮肤")
    )

    assert result.reply is not None
    assert result.reply.image == b"image:101"
    assert result.reply.text == (
        "💎【皮肤】\n"
        "所属精灵：精灵\n"
        "所属系列：周年\n"
        "礼卡价格：20\n"
        "售价：100"
    )


@pytest.mark.asyncio
async def test_single_pet_info_query_renders_image() -> None:
    data = FakeData()
    pet = _pet(1, "精灵")
    data.pets = (pet,)
    rendered: list[Any] = []

    result = await _service(data, rendered).search_info("精灵")

    assert result.reply is not None
    assert result.reply.image == b"rendered:1"
    assert rendered == [pet]


@pytest.mark.asyncio
async def test_pet_info_query_renders_before_data_session_closes() -> None:
    data = FakeData()
    pet = SessionBoundPet(data)
    data.pets = (pet,)

    async def render(session_bound_pet: PetORM) -> bytes:
        _ = session_bound_pet.base_stats
        return b"rendered"

    service = PetQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages()),
        render,
    )

    result = await service.search_info("精灵")

    assert result.reply is not None
    assert result.reply.image == b"rendered"
    assert data.session_active is False


@pytest.mark.asyncio
async def test_pet_info_selection_renders_before_data_session_closes() -> None:
    data = FakeData()
    pet = SessionBoundPet(data)
    data.pets = (pet,)

    async def render(session_bound_pet: PetORM) -> bytes:
        _ = session_bound_pet.base_stats
        return b"rendered"

    service = PetQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages()),
        render,
    )

    result = await service.select_info(pet.id)

    assert result.reply is not None
    assert result.reply.image == b"rendered"
    assert data.session_active is False


@pytest.mark.asyncio
async def test_pet_info_selection_reports_missing_pet() -> None:
    result = await _service(FakeData()).select_info(99)

    assert result.message == (
        "❌未找到精灵 99（这是一个bug，请反馈给开发者）"
    )
