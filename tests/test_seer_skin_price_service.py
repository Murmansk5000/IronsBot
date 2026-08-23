from sqlmodel import Session, create_engine

from ironsbot.services.seer.skin_price import (
    SkinShopPrice,
    SkinStorePrice,
    _format_skin_price_lines,
    load_active_skin_store_prices,
)

EXPECTED_STORE_PRICE = 298


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

    assert _format_skin_price_lines(
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

    assert _format_skin_price_lines(
        shop_price=shop_price,
        store_prices=[],
        existing_card_price=88,
    ) == ""


def test_load_active_skin_store_prices_reads_current_rows_in_one_batch() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE skin_store_price (
                skin_id INTEGER,
                pool_id INTEGER,
                price INTEGER,
                original_price INTEGER,
                discount_rate INTEGER,
                selected_price INTEGER,
                ticket_id INTEGER,
                ticket_num INTEGER,
                start_time INTEGER,
                end_time INTEGER,
                row_index INTEGER
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO skin_store_price VALUES
                (1, 1, 298, 398, 0, 0, 1727935, 20, 0, 0, 0),
                (1, 2, 199, 299, 0, 0, 1727935, 10, 0, 0, 0),
                (2, 1, 198, 298, 0, 0, 1727935, 20, 0, 1, 0)
            """
        )

    with Session(engine) as session:
        prices = load_active_skin_store_prices(session, skin_ids=(1, 2, 1))

    assert set(prices) == {1}
    assert prices[1].pool_id == 1
    assert prices[1].price == EXPECTED_STORE_PRICE
