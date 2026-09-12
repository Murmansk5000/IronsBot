import pytest
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.skin_price_repository import load_skin_details
from ironsbot.services.seer.data import PublishedDataIncompleteError
from ironsbot.services.seer.skin_price import (
    SkinShopPrice,
    SkinStorePrice,
    format_skin_price_lines,
)

SKIN_RESOURCE_ID = 1400101


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
