from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.extensions.contracts import PlayerLineupSlot
from ironsbot.integrations.seer_data import player_lineup_entries as lineup
from ironsbot.integrations.seer_data.pet_forms import PetFormCatalog, load_pet_forms

_EMPEROR_FORM_RESOURCE = 2900871
_LIGHT_SKIN_RESOURCE = 1400889
_EMPEROR_SKIN_RESOURCE = 1400871


def test_legacy_release_does_not_guess_forms_or_families() -> None:
    with Session(create_engine("sqlite://")) as session:
        forms = load_pet_forms(session)
    assert forms.resource(4950, 100871) is None
    assert forms.shares_skin(3311, 3311)
    assert not forms.shares_skin(13311, 3311)
    assert not forms.shares_skin(7, 0)


@pytest.mark.parametrize(
    ("pet_id", "skin_id", "expected"),
    [
        (4950, 100871, 2900871),
        (3393, 100000, 290003393),
        (4677, 100000, 290004677),
        (4950, 871, None),
        (4950, 200871, None),
        (7, 100000, None),
    ],
)
def test_official_form_lookup(pet_id: int, skin_id: int, expected: int | None) -> None:
    forms = PetFormCatalog(
        {(0, 871, 1): 2900871, (3393, 0, 1): 290003393, (4677, 0, 1): 290004677},
        frozenset(),
    )
    assert forms.resource(pet_id, skin_id) == expected


def test_lineup_normalizes_skin_and_uses_only_published_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lineup, "load_peak_pool_snapshots", lambda *_args, **_kw: ())
    monkeypatch.setattr(lineup, "load_peak_master_pool_snapshots", lambda *_: ())
    with Session(create_engine("sqlite://")) as session:
        for sql in (
            "CREATE TABLE pet_form_resource (pet_id, skin_id, form_index, resource_id)",
            "INSERT INTO pet_form_resource VALUES (0, 871, 1, 2900871)",
            "CREATE TABLE pet_form_member (canonical_pet_id, pet_id)",
            "INSERT INTO pet_form_member VALUES (3311,3311),(3311,13311)",
            "CREATE TABLE skin_image_resolution (skin_id, head_resource_id, "
            "body_resource_id, head_resolution, body_resolution, source_pet_id)",
        ):
            session.execute(text(sql))
        pets = [
            SimpleNamespace(
                id=id_, name="test", resource_id=id_, type=SimpleNamespace(id=1)
            )
            for id_ in (4950, 13311, 3312)
        ]
        skins = [
            SimpleNamespace(
                id=id_, pet_id=owner, name="skin", resource_id=1400000 + id_
            )
            for id_, owner in ((871, 4950), (889, 3311))
        ]
        exec_mock = Mock(side_effect=[pets, skins])
        monkeypatch.setattr(session, "exec", exec_mock)
        data = SimpleNamespace(query=lambda operation: nullcontext(operation(session)))
        entries = lineup.PublishedPlayerLineupEntryResolver(cast("Any", data)).resolve(
            (
                PlayerLineupSlot(4950, 100, 1, 100871),
                PlayerLineupSlot(13311, 100, 1, 889),
                PlayerLineupSlot(3312, 100, 1, 889),
            )
        )
        skin_query = exec_mock.call_args_list[-1].args[0].compile().params
        assert set(next(iter(skin_query.values()))) == {871, 889}
    assert entries[0].resource_id == _EMPEROR_FORM_RESOURCE and entries[0].complete
    assert (
        entries[1].resource_id == _LIGHT_SKIN_RESOURCE
        and entries[1].skin_name == "skin"
    )
    assert entries[2].resource_id == 0 and not entries[2].complete


def test_missing_form_mapping_retains_base_skin() -> None:
    slot = PlayerLineupSlot(4950, 100, 1, 900871)
    skin = SimpleNamespace(pet_id=4950, resource_id=1400871)
    assert (
        lineup._resource_id(slot, None, skin, None, PetFormCatalog({}, frozenset()))
        == _EMPEROR_SKIN_RESOURCE
    )
