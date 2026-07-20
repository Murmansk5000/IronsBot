# SPDX-License-Identifier: MIT
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.services.seer.effect_description import load_effect_descriptions


def test_load_effect_descriptions_uses_first_description_per_name() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE effect_description (
                    effect_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO effect_description (effect_id, name, description)
                VALUES
                    (544, '冥妖之悼', '第一条解释'),
                    (545, '幽迹之秘', '第二条解释'),
                    (546, '冥妖之悼', '重复解释')
                """
            )
        )

    with Session(engine) as session:
        descriptions = load_effect_descriptions(session)

    assert descriptions == {
        "冥妖之悼": "第一条解释",
        "幽迹之秘": "第二条解释",
    }


def test_load_effect_descriptions_allows_an_older_database_without_table() -> None:
    with Session(create_engine("sqlite://")) as session:
        assert load_effect_descriptions(session) == {}
