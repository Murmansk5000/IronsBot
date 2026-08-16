# SPDX-License-Identifier: MIT
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from seerapi_models.pet.petbook import PetEncyclopediaEntryORM
from sqlmodel import Session

from ironsbot.integrations.seer_data import pet_info_repository
from ironsbot.services.seer.pet_info_views import (
    PetDerivedDisplayData,
    PetStatsSnapshot,
)


@pytest.mark.parametrize("has_encyclopedia", [True, False])
def test_repository_detaches_encyclopedia_fields(
    monkeypatch: pytest.MonkeyPatch, *, has_encyclopedia: bool
) -> None:
    entry = PetEncyclopediaEntryORM(
        id=1,
        name="测试精灵",
        has_sound=False,
        height=12.5,
        weight=None,
        food="  能量果  ",
        introduction="  简介  ",
    )
    pet = SimpleNamespace(
        id=1,
        name="测试精灵",
        resource_id=1,
        gender=SimpleNamespace(id=0),
        type=SimpleNamespace(id=1, name="普通"),
        encyclopedia=entry if has_encyclopedia else None,
        skill_links=[],
        soulmark=[],
        base_stats=object(),
        advance=None,
    )
    session = Mock(spec=Session)
    session.get.return_value = pet
    monkeypatch.setattr(
        pet_info_repository,
        "_snapshot_stats",
        lambda _: PetStatsSnapshot(1, 1, 1, 1, 1, 1),
    )
    monkeypatch.setattr(pet_info_repository, "_load_partner", lambda *_: None)
    monkeypatch.setattr(
        pet_info_repository,
        "load_pet_derived_display_data",
        lambda *_args, **_kwargs: PetDerivedDisplayData((), (), ()),
    )
    result = pet_info_repository.PetInfoRepository().load(cast("Session", session), 1)
    assert result is not None
    entry.height = 99.0
    entry.food = "changed"
    assert result.pet.height == (12.5 if has_encyclopedia else None)
    assert result.pet.weight is None
    assert result.pet.food == ("能量果" if has_encyclopedia else None)
    assert result.pet.introduction == ("简介" if has_encyclopedia else "")
