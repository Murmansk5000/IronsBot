import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.skin_price_repository import (
    load_active_skin_store_prices,
    load_skin_details,
)
from ironsbot.services.seer.data import PublishedDataIncompleteError
from ironsbot.services.seer.skin_price import (
    SkinShopPrice,
    SkinStorePrice,
    format_skin_price_lines,
)

SKIN_RESOURCE_ID = 1400101
ACTIVE_PRICE = 100
EXPIRED_SKIN_ID = 2
OPEN_ENDED_PRICE = 300


def test_skin_details_rejects_database_without_published_price_tables() -> None:
    with (
        Session(create_engine("sqlite://")) as session,
        pytest.raises(PublishedDataIncompleteError) as raised,
    ):
        load_skin_details(session, resource_id=SKIN_RESOURCE_ID)

    assert raised.value.component == "skin_price"
    assert raised.value.entity_id == SKIN_RESOURCE_ID


def test_format_skin_price_lines_dedupes_and_formats_prices() -> None:
    shop_price = SkinShopPrice(
        skin_id=1,
        resource_id=10,
        card_price=88,
        diamond_price=200,
        original_price=300,
    )
    store_price = SkinStorePrice(
        skin_id=1,
        pool_id=2,
        price=150,
        original_price=200,
        discount_rate=0,
        selected_price=180,
        ticket_id=1,
        ticket_num=3,
        start_time=0,
        end_time=0,
    )

    assert format_skin_price_lines(
        shop_price=shop_price,
        store_prices=[store_price, store_price],
        existing_card_price=0,
    ) == (
        "礼卡价格：88\n"
        "钻石价格：200钻（原价300钻）\n"
        "幸运橱窗：150钻（原价200钻）；自选180钻；"
        "最多用3张风尚券，最低120钻\n"
    )


def test_format_skin_price_lines_omits_duplicate_card_price() -> None:
    shop_price = SkinShopPrice(
        skin_id=1,
        resource_id=10,
        card_price=88,
        diamond_price=0,
        original_price=0,
    )

    assert (
        format_skin_price_lines(
            shop_price=shop_price,
            store_prices=[],
            existing_card_price=88,
        )
        == ""
    )


def test_active_lucky_window_prices_are_loaded_in_one_query() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(
            text(
                """
                CREATE TABLE skin_store_price (
                    skin_id INTEGER, pool_id INTEGER, price INTEGER,
                    original_price INTEGER, discount_rate INTEGER,
                    selected_price INTEGER, ticket_id INTEGER,
                    ticket_num INTEGER, start_time INTEGER, end_time INTEGER,
                    row_index INTEGER
                )
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO skin_store_price VALUES
                    (1, 2, 120, 150, 0, 0, 9, 2, 0, 0, 2),
                    (1, 1, 100, 150, 0, 0, 9, 1, 0, 0, 1),
                    (2, 1, 200, 0, 0, 0, 9, 0, 0, 50, 1),
                    (3, 1, 300, 0, 0, 0, 9, 0, 0, 0, 1)
                """
            )
        )

        prices = load_active_skin_store_prices(
            session,
            skin_ids=(1, 2, 3, 1),
            now=100,
        )

    assert prices[1].pool_id == 1
    assert prices[1].price == ACTIVE_PRICE
    assert EXPIRED_SKIN_ID not in prices
    assert prices[3].price == OPEN_ENDED_PRICE
