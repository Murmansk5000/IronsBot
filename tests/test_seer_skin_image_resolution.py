from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.services.seer.skin_image_resolution import (
    load_skin_image_resolutions,
)

_SKIN_SOUL_EMPEROR = 538
_SKIN_ETERNAL_FIST = 761
_UNRESOLVED_SKIN = 999
_PET_HEAVENLY_SOUL_EMPEROR = 3382
_PET_ETERNAL_FIST = 3197
_SOUL_EMPEROR_SKIN_RESOURCE = 1400538


def test_load_skin_image_resolutions_reads_per_kind_build_results() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(
            text(
                """
                CREATE TABLE skin_image_resolution (
                    skin_id INTEGER PRIMARY KEY,
                    head_resource_id INTEGER NOT NULL,
                    body_resource_id INTEGER NOT NULL,
                    head_resolution TEXT NOT NULL,
                    body_resolution TEXT NOT NULL,
                    source_pet_id INTEGER
                )
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO skin_image_resolution VALUES
                    (538, 3382, 1400538, 'unique_name_source', 'direct_skin', 3382),
                    (761, 3197, 3197, 'unique_name_source', 'unique_name_source', 3197)
                """
            )
        )

        rows = load_skin_image_resolutions(
            session,
            (_SKIN_SOUL_EMPEROR, _SKIN_ETERNAL_FIST, _UNRESOLVED_SKIN),
        )

    assert rows[_SKIN_SOUL_EMPEROR].head_resource_id == _PET_HEAVENLY_SOUL_EMPEROR
    assert rows[_SKIN_SOUL_EMPEROR].body_resource_id == _SOUL_EMPEROR_SKIN_RESOURCE
    assert rows[_SKIN_ETERNAL_FIST].head_resource_id == _PET_ETERNAL_FIST
    assert rows[_SKIN_ETERNAL_FIST].body_resource_id == _PET_ETERNAL_FIST
    assert _UNRESOLVED_SKIN not in rows


def test_load_skin_image_resolutions_falls_back_for_legacy_database() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        assert load_skin_image_resolutions(session, (_SKIN_SOUL_EMPEROR,)) == {}
