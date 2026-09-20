# SPDX-License-Identifier: GPL-3.0-or-later
"""Read published skin price facts without leaking ORM rows into services."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from seerapi_models import PetSkinORM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from ironsbot.services.seer.data import PublishedDataIncompleteError
from ironsbot.services.seer.skin_price import (
    MAX_PRICE_ROWS,
    SkinDetails,
    SkinShopPrice,
    SkinStorePrice,
    format_skin_price_lines,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlmodel import Session


def load_skin_details(session: Session, *, resource_id: int) -> SkinDetails | None:
    try:
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
        shop_price = _load_shop_price(session, int(model.id))
        store_prices = _load_store_prices(session, int(model.id))
        return SkinDetails(
            pet_name=str(model.pet.name),
            series_name=str(series_name),
            card_price=model.card_price,
            price_lines=format_skin_price_lines(
                shop_price=shop_price,
                store_prices=store_prices,
                existing_card_price=model.card_price or 0,
            ),
        )
    except SQLAlchemyError as error:
        raise PublishedDataIncompleteError(
            "skin_price", entity_id=resource_id
        ) from error


def _load_shop_price(session: Session, skin_id: int) -> SkinShopPrice | None:
    row = session.execute(
        text(
            """
            SELECT skin_id, resource_id, card_price, diamond_price, original_price
            FROM skin_shop_price WHERE skin_id = :skin_id LIMIT 1
            """
        ),
        {"skin_id": skin_id},
    ).first()
    return None if row is None else SkinShopPrice(**_price_mapping(row))


def _load_store_prices(session: Session, skin_id: int) -> list[SkinStorePrice]:
    now = int(time.time())
    rows = session.execute(
        text(
            """
            SELECT skin_id, pool_id, price, original_price, discount_rate,
                   selected_price, ticket_id, ticket_num, start_time, end_time
            FROM skin_store_price
            WHERE skin_id = :skin_id
              AND (start_time <= 0 OR start_time <= :now)
              AND (end_time <= 0 OR :now <= end_time)
            ORDER BY pool_id, skin_id, row_index LIMIT :limit
            """
        ),
        {"skin_id": skin_id, "now": now, "limit": MAX_PRICE_ROWS},
    ).all()
    return [SkinStorePrice(**_price_mapping(row)) for row in rows]


def load_active_skin_store_prices(
    session: Session,
    *,
    skin_ids: tuple[int, ...],
    now: int | None = None,
) -> dict[int, SkinStorePrice]:
    """Load the first active lucky-window price for each skin in one query."""

    unique_ids = tuple(dict.fromkeys(skin_id for skin_id in skin_ids if skin_id > 0))
    if not unique_ids:
        return {}
    placeholders = ", ".join(f":skin_id_{index}" for index in range(len(unique_ids)))
    params = {f"skin_id_{index}": skin_id for index, skin_id in enumerate(unique_ids)}
    params["now"] = int(time.time()) if now is None else now
    try:
        rows = session.execute(
            text(
                f"""
                SELECT skin_id, pool_id, price, original_price, discount_rate,
                       selected_price, ticket_id, ticket_num, start_time, end_time
                FROM skin_store_price
                WHERE skin_id IN ({placeholders})
                  AND (start_time <= 0 OR start_time <= :now)
                  AND (end_time <= 0 OR :now <= end_time)
                ORDER BY skin_id, pool_id, row_index
                """
            ),
            params,
        ).all()
    except SQLAlchemyError as error:
        raise PublishedDataIncompleteError("skin_price") from error

    prices: dict[int, SkinStorePrice] = {}
    for row in rows:
        price = SkinStorePrice(**_price_mapping(row))
        prices.setdefault(price.skin_id, price)
    return prices


def _price_mapping(row: Any) -> dict[str, int]:
    mapping = cast(
        "Mapping[str, Any]", row._mapping if hasattr(row, "_mapping") else row
    )
    return {key: int(value or 0) for key, value in mapping.items()}
