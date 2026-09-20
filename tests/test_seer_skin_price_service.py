from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.skin_price_repository import (
    _load_store_prices,
    load_active_skin_store_prices,
    load_skin_details,
)
from ironsbot.services.seer.data import PublishedDataIncompleteError
from ironsbot.services.seer.skin_price import (
    SkinModelPrice,
    SkinShopPrice,
    SkinStorePrice,
    format_lucky_window_price_lines,
    format_skin_price_lines,
    merge_skin_price_facts,
)

SKIN_RESOURCE_ID = 1400101
ACTIVE_PRICE = 100
EXPIRED_SKIN_ID = 2
OPEN_ENDED_PRICE = 300
CARD_PRICE = 88
MODEL_STORE_PRICE = 198
MODEL_STORE_ORIGINAL = 298
MODEL_TICKETS = 10
COUPON_DISCOUNT = 20
FIRST_COUPON_RATE = 10
SECOND_COUPON_RATE = 7
SMALL_PRICE = 15


@pytest.mark.parametrize(
    "amount,quantity,rate,ticket_text,minimum",
    [
        (100, 2, 7, "2张星辉券，最低86钻", 86),
        (15, 2, 10, "2张星辉券，可抵扣20钻", 0),
        (20, 2, 10, "2张星辉券，可抵扣20钻", 0),
        (100, 2, None, "2张星辉券", None),
        (100, 2, 0, "2张星辉券", None),
        (100, 0, 10, None, None),
        (100, -1, 10, None, None),
        (0, 2, 10, "2张星辉券，可抵扣20钻", None),
        (-1, 2, 10, "2张星辉券，可抵扣20钻", None),
    ],
)
def test_price_text_and_image_keep_existing_exact_wording(
    amount: int,
    quantity: int,
    rate: int | None,
    ticket_text: str | None,
    minimum: int | None,
) -> None:
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowOffer
    from ironsbot.services.seer.rendering.lucky_skin_window import (
        present_lucky_skin_window,
    )

    store = SkinStorePrice(1, 1, amount, 150, 0, 120, 9, quantity, 0, 0, "星辉券", rate)
    detail = format_skin_price_lines(
        shop_price=None, store_prices=[store], existing_card_price=0
    )
    window = format_lucky_window_price_lines(store)
    card = present_lucky_skin_window(
        (LuckySkinWindowOffer(1, 10, "皮肤", watched=False, store_price=store),),
        {},
        ticket_icons={},
        diamond_icon=None,
    ).cards[0]

    if amount > 0:
        quote = f"{amount}钻（原价150钻）"
        expected_detail = f"幸运橱窗：{quote}；自选120钻"
        expected_window = (f"橱窗价：{quote}",)
        if ticket_text is not None:
            expected_detail += f"；最多用{ticket_text}"
            expected_window += (f"最多用{ticket_text}",)
        assert detail == expected_detail + "\n"
        assert window == expected_window
        assert card.price_text == f"橱窗价 {quote}"
    else:
        assert detail == "幸运橱窗：自选120钻\n"
        assert window == ("橱窗价格暂未获取",)
        assert card.price_text is None
    assert card.ticket_text == (
        f"最多{ticket_text}" if ticket_text is not None else None
    )
    assert card.minimum_diamonds == minimum
    assert card.price_error is (amount <= 0)


@pytest.mark.parametrize(
    "ticket_id,ticket_name,expected,ticket_diamonds",
    [
        (1727935, "风尚券", "风尚券", 10),
        (1727935, "风尚券", "风尚券", None),
        (9, "风尚券", "风尚券", None),
        (9, "星辉券", "星辉券", None),
        (9, "星辉券", "星辉券", 7),
        (9, None, "券道具9", None),
        (0, None, "优惠券", None),
    ],
)
@pytest.mark.parametrize("price", [15, 100])
def test_all_price_presentations_use_the_resolved_coupon(
    ticket_id: int,
    ticket_name: str | None,
    expected: str,
    ticket_diamonds: int | None,
    price: int,
) -> None:
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowOffer
    from ironsbot.services.seer.rendering.lucky_skin_window import (
        present_lucky_skin_window,
    )

    store = SkinStorePrice(
        1, 1, price, 0, 0, 0, ticket_id, 2, 0, 0, ticket_name, ticket_diamonds
    )
    lines = format_skin_price_lines(
        shop_price=None, store_prices=[store], existing_card_price=0
    )
    window = format_lucky_window_price_lines(store)
    card = present_lucky_skin_window(
        (LuckySkinWindowOffer(1, 10, "皮肤", watched=False, store_price=store),),
        {},
        ticket_icons={},
        diamond_icon=None,
    ).cards[0]
    for rendered in (lines, window[-1], card.ticket_text or ""):
        assert expected in rendered
        if ticket_diamonds == FIRST_COUPON_RATE:
            assert ("最低80钻" if price > COUPON_DISCOUNT else "可抵扣20钻") in rendered
        elif ticket_diamonds == SECOND_COUPON_RATE:
            assert ("最低1钻" if price == SMALL_PRICE else "最低86钻") in rendered
        else:
            assert "最低" not in rendered
            assert "抵扣" not in rendered
    if ticket_diamonds is None:
        assert card.minimum_diamonds is None


@pytest.mark.parametrize("zero_details", [False, True])
def test_model_prices_supplement_missing_or_zero_details(*, zero_details: bool) -> None:
    shop, stores = merge_skin_price_facts(
        skin_id=1,
        resource_id=10,
        model=SkinModelPrice(88, 300, 298, 198, 10),
        shop=SkinShopPrice(1, 10, 0, 0, 0) if zero_details else None,
        stores=[SkinStorePrice(1, 2, 0, 0, 0, 0, 0, 0, 0, 0)] if zero_details else [],
    )
    assert shop.card_price == CARD_PRICE
    assert shop.diamond_price == OPEN_ENDED_PRICE
    assert len(stores) == 1
    assert stores[0].price == MODEL_STORE_PRICE
    assert stores[0].original_price == MODEL_STORE_ORIGINAL
    assert stores[0].ticket_num == MODEL_TICKETS
    assert format_skin_price_lines(
        shop_price=shop,
        store_prices=stores,
        existing_card_price=shop.card_price,
    ) == ("钻石价格：300钻\n幸运橱窗：198钻（原价298钻）；最多用10张优惠券\n")


def test_valid_detail_prices_win_over_conflicting_model() -> None:
    detail_shop = SkinShopPrice(1, 10, 88, 200, 300)
    detail_store = SkinStorePrice(1, 2, 150, 200, 0, 180, 1, 3, 0, 0)
    shop, stores = merge_skin_price_facts(
        skin_id=1,
        resource_id=10,
        model=SkinModelPrice(99, 999, 999, 888, 50),
        shop=detail_shop,
        stores=[detail_store],
    )
    assert shop == detail_shop
    assert stores == [detail_store]


def test_model_supplements_only_missing_fields_of_same_store() -> None:
    detail = SkinStorePrice(1, 2, 150, 0, 0, 180, 9, 0, 10, 20)
    _, stores = merge_skin_price_facts(
        skin_id=1,
        resource_id=10,
        model=SkinModelPrice(None, None, 200, 198, 3),
        shop=None,
        stores=[detail],
    )
    assert stores == [replace(detail, original_price=200, ticket_num=3)]


def test_multiple_pool_offers_are_not_guessed_from_model() -> None:
    detail = SkinStorePrice(1, 2, 150, 0, 0, 0, 9, 0, 0, 0)
    details = [detail, replace(detail, pool_id=3)]
    _, stores = merge_skin_price_facts(
        skin_id=1,
        resource_id=10,
        model=SkinModelPrice(None, None, 200, 198, 3),
        shop=None,
        stores=details,
    )
    assert stores == details


def test_empty_model_does_not_invent_prices() -> None:
    shop, stores = merge_skin_price_facts(
        skin_id=1,
        resource_id=10,
        model=SkinModelPrice(None, None, None, None, None),
        shop=None,
        stores=[],
    )
    assert (
        format_skin_price_lines(
            shop_price=shop, store_prices=stores, existing_card_price=0
        )
        == ""
    )


def test_repository_uses_merged_card_and_diamond_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ironsbot.integrations.seer_data import skin_price_repository

    session = Mock(spec=Session)
    session.exec.return_value.first.return_value = SimpleNamespace(
        id=1,
        resource_id=10,
        series=None,
        pet=SimpleNamespace(name="测试"),
        card_price=99,
        diamond_price=300,
        skinhouse_price=298,
        discounted_skinhouse_price=198,
        ticket_num=10,
    )
    monkeypatch.setattr(
        skin_price_repository,
        "_load_shop_price",
        lambda *_: SkinShopPrice(1, 10, 88, 0, 0),
    )
    monkeypatch.setattr(skin_price_repository, "_load_store_prices", lambda *_: [])
    result = load_skin_details(cast("Session", session), resource_id=10)
    assert result is not None
    assert result.card_price == CARD_PRICE
    assert "礼卡价格" not in result.price_lines
    assert "钻石价格：300钻" in result.price_lines
    assert result.price_lines.count("幸运橱窗") == 1


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
        ticket_id=1727935,
        ticket_name="风尚券",
        ticket_diamonds=10,
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
        session.execute(text("CREATE TABLE item (id INTEGER PRIMARY KEY, name TEXT)"))
        session.execute(text("INSERT INTO item VALUES (9, '星辉券')"))
        session.execute(
            text(
                "CREATE TABLE skin_ticket_rule (ticket_id INTEGER PRIMARY KEY, "
                "diamonds_per_ticket INTEGER NOT NULL CHECK(diamonds_per_ticket>0), "
                "source TEXT NOT NULL, source_text TEXT NOT NULL)"
            )
        )
        session.execute(
            text(
                "INSERT INTO skin_ticket_rule VALUES "
                "(9,7,'item','测试幸运橱窗抵扣规则')"
            )
        )
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

        statements: list[str] = []
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _c, _cursor, statement, _p, _ctx, _many: statements.append(
                statement
            ),
        )
        prices = load_active_skin_store_prices(
            session,
            skin_ids=(1, 2, 3, 1),
            now=100,
        )
        assert len(statements) == 1
        assert prices[1].ticket_name == "星辉券"
        assert prices[1].ticket_diamonds == SECOND_COUPON_RATE
        assert "最低93钻" in format_lucky_window_price_lines(prices[1])[-1]
        assert "星辉券" in format_lucky_window_price_lines(prices[1])[-1]
        details = _load_store_prices(session, 1)
        assert details[0].ticket_name == "星辉券"
        assert details[0].ticket_diamonds == SECOND_COUPON_RATE
        session.execute(text("DELETE FROM skin_ticket_rule"))
        no_rule = load_active_skin_store_prices(session, skin_ids=(1,), now=100)[1]
        assert no_rule.ticket_diamonds is None
        assert "最低" not in format_lucky_window_price_lines(no_rule)[-1]
        session.execute(text("DELETE FROM item"))
        unknown = load_active_skin_store_prices(session, skin_ids=(1,), now=100)[1]
        assert unknown.ticket_name is None
        assert "券道具9" in format_lucky_window_price_lines(unknown)[-1]

    assert prices[1].pool_id == 1
    assert prices[1].price == ACTIVE_PRICE
    assert EXPIRED_SKIN_ID not in prices
    assert prices[3].price == OPEN_ENDED_PRICE
