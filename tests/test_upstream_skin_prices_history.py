from ironsbot.services.seer.skin_price import (
    SkinModelPrice,
    SkinShopPrice,
    merge_skin_price_facts,
)


def test_model_fills_missing_diamond_price_without_second_store() -> None:
    shop, stores = merge_skin_price_facts(
        skin_id=1,
        resource_id=2,
        model=SkinModelPrice(None, 300, 398, 298, 20),
        shop=SkinShopPrice(1, 2, 0, 0, 0),
        stores=[],
    )
    assert (shop.diamond_price,) == (300,)
    assert [
        (store.price, store.original_price, store.ticket_num) for store in stores
    ] == [(298, 398, 20)]


def test_detailed_shop_price_takes_precedence() -> None:
    shop, _ = merge_skin_price_facts(
        skin_id=1,
        resource_id=2,
        model=SkinModelPrice(10, 300, None, None, None),
        shop=SkinShopPrice(1, 2, 20, 400, 500),
        stores=[],
    )
    assert (shop.card_price, shop.diamond_price) == (20, 400)
