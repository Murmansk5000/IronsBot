# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from seerapi_models import PetSkinORM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlmodel import Session

FASHION_TICKET_VALUE = 10
MAX_PRICE_ROWS = 3
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SkinStorePrice:
    skin_id: int
    pool_id: int
    price: int
    original_price: int
    discount_rate: int
    selected_price: int
    ticket_id: int
    ticket_num: int
    start_time: int
    end_time: int


@dataclass(frozen=True, slots=True)
class SkinShopPrice:
    skin_id: int
    resource_id: int
    card_price: int
    diamond_price: int
    original_price: int


@dataclass(frozen=True, slots=True)
class SkinDetails:
    pet_name: str
    series_name: str
    card_price: int | None
    price_lines: str


def load_skin_details(
    session: Session,
    *,
    resource_id: int,
) -> SkinDetails | None:
    model = session.exec(
        select(PetSkinORM).where(PetSkinORM.resource_id == resource_id)
    ).first()
    if model is None:
        return None

    series_name = "无"
    if model.series:
        series_name = model.series.name
        if model.sub_type:
            series_name += f" - {model.sub_type.name}"

    return SkinDetails(
        pet_name=model.pet.name,
        series_name=series_name,
        card_price=model.card_price,
        price_lines=_format_skin_price_lines_for_session(
            session,
            model.id,
            existing_card_price=model.card_price,
        ),
    )


def _format_skin_price_lines_for_session(
    session: Session,
    skin_id: int,
    *,
    existing_card_price: int | None = None,
) -> str:
    try:
        shop_price = _load_shop_price(session, skin_id)
        store_prices = _load_store_prices(session, skin_id)
    except SQLAlchemyError:
        logger.exception("failed to load skin price rows from IronsBot SQLite")
        return ""

    return _format_skin_price_lines(
        shop_price=shop_price,
        store_prices=store_prices,
        existing_card_price=existing_card_price or 0,
    )


def _load_shop_price(
    session: Session,
    skin_id: int,
) -> SkinShopPrice | None:
    row = session.execute(
        text(
            """
            SELECT skin_id, resource_id, card_price, diamond_price, original_price
            FROM skin_shop_price
            WHERE skin_id = :skin_id
            LIMIT 1
            """
        ),
        params={"skin_id": skin_id},
    ).first()
    if row is None:
        return None

    mapping = cast(
        "Mapping[str, Any]",
        row._mapping if hasattr(row, "_mapping") else row,
    )
    return SkinShopPrice(
        skin_id=int(mapping["skin_id"]),
        resource_id=int(mapping["resource_id"] or 0),
        card_price=int(mapping["card_price"] or 0),
        diamond_price=int(mapping["diamond_price"] or 0),
        original_price=int(mapping["original_price"] or 0),
    )


def _load_store_prices(
    session: Session,
    skin_id: int,
) -> list[SkinStorePrice]:
    now = int(time.time())
    rows = session.execute(
        text(
            """
            SELECT
                skin_id,
                pool_id,
                price,
                original_price,
                discount_rate,
                selected_price,
                ticket_id,
                ticket_num,
                start_time,
                end_time
            FROM skin_store_price
            WHERE skin_id = :skin_id
              AND (start_time <= 0 OR start_time <= :now)
              AND (end_time <= 0 OR :now <= end_time)
            ORDER BY pool_id, skin_id, row_index
            LIMIT :limit
            """
        ),
        params={"skin_id": skin_id, "now": now, "limit": MAX_PRICE_ROWS},
    ).all()

    prices: list[SkinStorePrice] = []
    for row in rows:
        mapping = cast(
            "Mapping[str, Any]",
            row._mapping if hasattr(row, "_mapping") else row,
        )
        prices.append(
            SkinStorePrice(
                skin_id=int(mapping["skin_id"]),
                pool_id=int(mapping["pool_id"] or 0),
                price=int(mapping["price"] or 0),
                original_price=int(mapping["original_price"] or 0),
                discount_rate=int(mapping["discount_rate"] or 0),
                selected_price=int(mapping["selected_price"] or 0),
                ticket_id=int(mapping["ticket_id"] or 0),
                ticket_num=int(mapping["ticket_num"] or 0),
                start_time=int(mapping["start_time"] or 0),
                end_time=int(mapping["end_time"] or 0),
            )
        )
    return prices


def load_active_skin_store_prices(
    session: Session,
    *,
    skin_ids: Iterable[int],
) -> dict[int, SkinStorePrice]:
    """Load one active lucky-store price for each requested skin in one query."""

    unique_ids = tuple(dict.fromkeys(int(skin_id) for skin_id in skin_ids))
    if not unique_ids:
        return {}

    placeholders = ", ".join(f":skin_id_{index}" for index in range(len(unique_ids)))
    params: dict[str, int] = {
        f"skin_id_{index}": skin_id for index, skin_id in enumerate(unique_ids)
    }
    params["now"] = int(time.time())
    rows = session.execute(
        text(
            f"""
            SELECT
                skin_id,
                pool_id,
                price,
                original_price,
                discount_rate,
                selected_price,
                ticket_id,
                ticket_num,
                start_time,
                end_time
            FROM skin_store_price
            WHERE skin_id IN ({placeholders})
              AND (start_time <= 0 OR start_time <= :now)
              AND (end_time <= 0 OR :now <= end_time)
            ORDER BY skin_id, pool_id, row_index
            """
        ),
        params=params,
    ).all()

    prices: dict[int, SkinStorePrice] = {}
    for row in rows:
        mapping = cast(
            "Mapping[str, Any]",
            row._mapping if hasattr(row, "_mapping") else row,
        )
        skin_id = int(mapping["skin_id"])
        prices.setdefault(
            skin_id,
            SkinStorePrice(
                skin_id=skin_id,
                pool_id=int(mapping["pool_id"] or 0),
                price=int(mapping["price"] or 0),
                original_price=int(mapping["original_price"] or 0),
                discount_rate=int(mapping["discount_rate"] or 0),
                selected_price=int(mapping["selected_price"] or 0),
                ticket_id=int(mapping["ticket_id"] or 0),
                ticket_num=int(mapping["ticket_num"] or 0),
                start_time=int(mapping["start_time"] or 0),
                end_time=int(mapping["end_time"] or 0),
            ),
        )
    return prices


def _format_skin_price_lines(
    *,
    shop_price: SkinShopPrice | None,
    store_prices: list[SkinStorePrice],
    existing_card_price: int,
) -> str:
    lines: list[str] = []
    if shop_price and shop_price.card_price and not existing_card_price:
        lines.append(f"礼卡价格：{shop_price.card_price}")
    if shop_price and shop_price.diamond_price:
        lines.append(_format_shop_price(shop_price))

    for price in store_prices:
        line = _format_store_price(price)
        if line:
            lines.append(line)

    return "".join(f"{line}\n" for line in _dedupe_lines(lines))


def _format_shop_price(price: SkinShopPrice) -> str:
    if price.original_price and price.original_price != price.diamond_price:
        return f"钻石价格：{price.diamond_price}钻（原价{price.original_price}钻）"
    return f"钻石价格：{price.diamond_price}钻"


def _format_store_price(price: SkinStorePrice) -> str:
    if price.price <= 0 and price.selected_price <= 0:
        return ""

    parts: list[str] = []
    if price.price > 0:
        if price.original_price > 0 and price.original_price != price.price:
            parts.append(f"{price.price}钻（原价{price.original_price}钻）")
        else:
            parts.append(f"{price.price}钻")
    if price.selected_price > 0 and price.selected_price != price.price:
        parts.append(f"自选{price.selected_price}钻")
    if price.ticket_num > 0 and price.price > 0:
        ticket_discount = price.ticket_num * FASHION_TICKET_VALUE
        if ticket_discount < price.price:
            minimum = price.price - ticket_discount
            parts.append(f"最多用{price.ticket_num}张风尚券，最低{minimum}钻")
        else:
            parts.append(f"最多用{price.ticket_num}张风尚券，可抵扣{ticket_discount}钻")

    return "幸运橱窗：" + "；".join(parts)


def _dedupe_lines(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result
