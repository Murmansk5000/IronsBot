# SPDX-License-Identifier: MIT
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.services.seer.item_exchange_price import load_item_exchange_prices

ACTIVATION_ITEM_ID = 1728296
CURRENCY_ITEM_ID = 1726710
EXCHANGE_PRICE = 2000
PURCHASE_LIMIT = 6


def _session_with_exchange_prices() -> Session:
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
                CREATE TABLE item_exchange_price (
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_entry_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    item_quantity INTEGER NOT NULL,
                    currency_item_id INTEGER NOT NULL,
                    currency_name TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    purchase_limit INTEGER,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (source_key, source_entry_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO item_exchange_price (
                    source_key,
                    source_name,
                    source_entry_id,
                    item_id,
                    item_name,
                    item_quantity,
                    currency_item_id,
                    currency_name,
                    amount,
                    purchase_limit,
                    start_time,
                    end_time,
                    updated_at
                )
                VALUES (
                    'battlepass_shop',
                    '战令商店',
                    1005,
                    1728296,
                    '双源魂蒂',
                    1,
                    1726710,
                    '共鸣锚点',
                    2000,
                    6,
                    0,
                    0,
                    0
                )
                """
            )
        )
    return Session(engine)


def test_load_item_exchange_prices_reads_currency_name_and_limit() -> None:
    with _session_with_exchange_prices() as session:
        prices = load_item_exchange_prices(session, [ACTIVATION_ITEM_ID])

    assert prices[ACTIVATION_ITEM_ID][0].source_name == "战令商店"
    assert prices[ACTIVATION_ITEM_ID][0].item_name == "双源魂蒂"
    assert prices[ACTIVATION_ITEM_ID][0].currency_name == "共鸣锚点"
    assert prices[ACTIVATION_ITEM_ID][0].amount == EXCHANGE_PRICE
    assert prices[ACTIVATION_ITEM_ID][0].purchase_limit == PURCHASE_LIMIT


def test_load_item_exchange_prices_ignores_expired_listings() -> None:
    with _session_with_exchange_prices() as session:
        session.execute(
            text(
                """
                INSERT INTO item_exchange_price (
                    source_key,
                    source_name,
                    source_entry_id,
                    item_id,
                    item_name,
                    item_quantity,
                    currency_item_id,
                    currency_name,
                    amount,
                    purchase_limit,
                    start_time,
                    end_time,
                    updated_at
                )
                VALUES (
                    'expired',
                    '过期商店',
                    1,
                    1728296,
                    '',
                    1,
                    1726710,
                    '共鸣锚点',
                    1,
                    NULL,
                    1,
                    1,
                    0
                )
                """
            )
        )

        prices = load_item_exchange_prices(session, [ACTIVATION_ITEM_ID])

    assert len(prices[ACTIVATION_ITEM_ID]) == 1
    assert prices[ACTIVATION_ITEM_ID][0].source_name == "战令商店"


def test_load_item_exchange_prices_allows_an_older_database_without_table() -> None:
    with Session(create_engine("sqlite://")) as session:
        assert load_item_exchange_prices(session, [ACTIVATION_ITEM_ID]) == {}


def test_load_item_exchange_prices_names_legacy_special_skill_currency() -> None:
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
                CREATE TABLE item_exchange_price (
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_entry_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    item_quantity INTEGER NOT NULL,
                    currency_item_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    purchase_limit INTEGER,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (source_key, source_entry_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO item_exchange_price VALUES (
                    'special_skill_shop', '追加技能商店', 1,
                    1727009, '魔灵密卷', 1, 1726992,
                    400, 1, 0, 0, 0
                )
                """
            )
        )

    with Session(engine) as session:
        prices = load_item_exchange_prices(session, [1727009])

    assert prices[1727009][0].source_name == "微光秘境"
    assert prices[1727009][0].currency_name == "共振晶体"
