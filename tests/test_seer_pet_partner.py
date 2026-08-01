# SPDX-License-Identifier: MIT
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.services.seer.pet_partner import load_pet_partner

CONTRACT_BADGE_COST = 8


def _session_with_pet_partner() -> Session:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE item (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE pet (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE skill (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE skillinpetorm (
                    pet_id INTEGER NOT NULL,
                    skill_id INTEGER NOT NULL,
                    skill_activation_item_id INTEGER
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE skill_activation_item (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    item_number INTEGER NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE pet_partner_group (
                    group_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    cost_item_id INTEGER NOT NULL,
                    cost_item_name TEXT NOT NULL,
                    cost_item_quantity INTEGER NOT NULL,
                    required_pet_count INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE pet_partner_member (
                    group_id INTEGER NOT NULL,
                    pet_id INTEGER NOT NULL,
                    display_order INTEGER NOT NULL,
                    PRIMARY KEY (group_id, pet_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE pet_partner_upgrade (
                    pet_id INTEGER PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    before_description TEXT NOT NULL,
                    after_description TEXT NOT NULL,
                    skill_id INTEGER,
                    source TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO item (id, name) VALUES (1722827, '契约徽章')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO pet (id, name) VALUES
                    (4329, '夜魔之神'),
                    (3491, '魔灵王')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO skill (id, name) VALUES (36696, '至暗·无量空邃')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO skill_activation_item (id, name, item_number)
                VALUES (1725370, '梦夜之源', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO skillinpetorm (pet_id, skill_id, skill_activation_item_id)
                VALUES (4329, 36696, 1725370)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO pet_partner_group (
                    group_id,
                    name,
                    cost_item_id,
                    cost_item_name,
                    cost_item_quantity,
                    required_pet_count,
                    source,
                    updated_at
                )
                VALUES (15, '源初之夜', 1722827, '契约徽章', 8, 2, 'test', 0)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO pet_partner_member (group_id, pet_id, display_order)
                VALUES (15, 4329, 1), (15, 3491, 2)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO pet_partner_upgrade (
                    pet_id,
                    group_id,
                    before_description,
                    after_description,
                    skill_id,
                    source,
                    updated_at
                )
                VALUES (4329, 15, '强化前魂印', '强化后魂印', 36696, 'test', 0)
                """
            )
        )
    return Session(engine)


def test_load_pet_partner_reads_cost_members_and_skill_item() -> None:
    with _session_with_pet_partner() as session:
        partner = load_pet_partner(session, 4329)

    assert partner is not None
    assert partner.name == "源初之夜"
    assert partner.cost_item_name == "契约徽章"
    assert partner.cost_item_quantity == CONTRACT_BADGE_COST
    assert [(member.pet_id, member.name) for member in partner.members] == [
        (4329, "夜魔之神"),
        (3491, "魔灵王"),
    ]
    assert partner.before_description == "强化后魂印"
    assert partner.after_description == "强化前魂印"
    assert partner.skill is not None
    assert partner.skill.name == "至暗·无量空邃"
    assert partner.skill.activation_item is not None
    assert partner.skill.activation_item.name == "梦夜之源"


def test_load_pet_partner_allows_an_older_database_without_tables() -> None:
    with Session(create_engine("sqlite://")) as session:
        assert load_pet_partner(session, 4329) is None
