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
    SkinModelPrice,
    SkinShopPrice,
    SkinStorePrice,
    format_skin_price_lines,
    merge_skin_price_facts,
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
        shop_price, store_prices = merge_skin_price_facts(
            skin_id=int(model.id),
            resource_id=int(model.resource_id),
            model=SkinModelPrice(
                card_price=model.card_price,
                diamond_price=model.diamond_price,
                skinhouse_price=model.skinhouse_price,
                discounted_skinhouse_price=model.discounted_skinhouse_price,
                ticket_num=model.ticket_num,
            ),
            shop=shop_price,
            stores=store_prices,
        )
        return SkinDetails(
            pet_name=str(model.pet.name),
            series_name=str(series_name),
            card_price=shop_price.card_price or None,
            price_lines=format_skin_price_lines(
                shop_price=shop_price,
                store_prices=store_prices,
                existing_card_price=shop_price.card_price,
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
    rule_value, rule_join = _ticket_rule_sql(session)
    rows = session.execute(
        text(
            f"""
            SELECT offer.skin_id, pool_id, price, original_price, discount_rate,
                   selected_price, offer.ticket_id, ticket_num, start_time, end_time,
                   item.name AS ticket_name,
                   {rule_value} AS ticket_diamonds
            FROM skin_store_price AS offer
            LEFT JOIN item ON item.id = offer.ticket_id
            {rule_join}
            WHERE offer.skin_id = :skin_id
              AND (start_time <= 0 OR start_time <= :now)
              AND (end_time <= 0 OR :now <= end_time)
            ORDER BY pool_id, skin_id, row_index LIMIT :limit
            """
        ),
        {"skin_id": skin_id, "now": now, "limit": MAX_PRICE_ROWS},
    ).all()
    return [_store_price(row) for row in rows]


def _ticket_rule_sql(session: Session) -> tuple[str, str]:
    """Optional pricing evidence must not block unrelated published data."""
    columns = {
        str(row[1])
        for row in session.execute(text("PRAGMA table_info(skin_ticket_rule)"))
    }
    if not {"ticket_id", "diamonds_per_ticket", "source", "source_text"} <= columns:
        return "NULL", ""
    return (
        "rule.diamonds_per_ticket",
        "LEFT JOIN skin_ticket_rule AS rule ON rule.ticket_id = offer.ticket_id",
    )


def load_active_skin_store_prices(
    session: Session,
    *,
    skin_ids: tuple[int, ...],
    now: int | None = None,
) -> dict[int, SkinStorePrice]:
    """Batch-load prices after one optional-rule schema check."""

    unique_ids = tuple(dict.fromkeys(skin_id for skin_id in skin_ids if skin_id > 0))
    if not unique_ids:
        return {}
    placeholders = ", ".join(f":skin_id_{index}" for index in range(len(unique_ids)))
    params = {f"skin_id_{index}": skin_id for index, skin_id in enumerate(unique_ids)}
    params["now"] = int(time.time()) if now is None else now
    try:
        rule_value, rule_join = _ticket_rule_sql(session)
        rows = session.execute(
            text(
                f"""
                SELECT offer.skin_id, pool_id, price, original_price, discount_rate,
                       selected_price, offer.ticket_id, ticket_num,
                       start_time, end_time,
                       item.name AS ticket_name,
                       {rule_value} AS ticket_diamonds
                FROM skin_store_price AS offer
                LEFT JOIN item ON item.id = offer.ticket_id
                {rule_join}
                WHERE offer.skin_id IN ({placeholders})
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
        price = _store_price(row)
        prices.setdefault(price.skin_id, price)
    return prices


def _price_mapping(row: Any) -> dict[str, int]:
    mapping = cast(
        "Mapping[str, Any]", row._mapping if hasattr(row, "_mapping") else row
    )
    return {
        key: int(value or 0)
        for key, value in mapping.items()
        if key not in {"ticket_name", "ticket_diamonds"}
    }


def _store_price(row: Any) -> SkinStorePrice:
    mapping = row._mapping
    name = mapping["ticket_name"]
    diamonds = mapping["ticket_diamonds"]
    return SkinStorePrice(
        **_price_mapping(row),
        ticket_name=str(name).strip() or None if name else None,
        ticket_diamonds=int(diamonds) if diamonds is not None else None,
    )
