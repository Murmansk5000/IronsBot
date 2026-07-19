# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlmodel import Session

ITEM_EXCHANGE_PRICE_TABLE = "item_exchange_price"
MAX_ITEM_EXCHANGE_PRICE_ROWS = 3
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ItemExchangePrice:
    source_name: str
    item_quantity: int
    currency_item_id: int
    currency_name: str
    amount: int
    purchase_limit: int | None


def load_item_exchange_prices(
    session: Session,
    item_ids: Iterable[int],
) -> dict[int, list[ItemExchangePrice]]:
    """Load current official exchange listings for a small set of item IDs.

    The enrichment table is built into IronsBot's data release. Older releases
    simply have no table, which means no price is shown rather than breaking a
    pet information card.
    """

    normalized_item_ids = sorted({item_id for item_id in item_ids if item_id > 0})
    if not normalized_item_ids:
        return {}

    statement = text(
        f"""
        SELECT
            exchange_price.item_id,
            exchange_price.source_name,
            exchange_price.item_quantity,
            exchange_price.currency_item_id,
            COALESCE(currency.name, '') AS currency_name,
            exchange_price.amount,
            exchange_price.purchase_limit
        FROM {ITEM_EXCHANGE_PRICE_TABLE} AS exchange_price
        LEFT JOIN item AS currency
            ON currency.id = exchange_price.currency_item_id
        WHERE exchange_price.item_id IN :item_ids
          AND (exchange_price.start_time <= 0 OR exchange_price.start_time <= :now)
          AND (exchange_price.end_time <= 0 OR :now <= exchange_price.end_time)
        ORDER BY
            exchange_price.item_id,
            exchange_price.source_name,
            exchange_price.amount,
            exchange_price.source_entry_id
        """
    ).bindparams(bindparam("item_ids", expanding=True))
    try:
        rows = session.execute(
            statement,
            {"item_ids": normalized_item_ids, "now": int(time.time())},
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "item exchange price data is unavailable in the current SQLite release",
            exc_info=True,
        )
        return {}

    result: dict[int, list[ItemExchangePrice]] = {}
    for row in rows:
        mapping = cast(
            "Mapping[str, Any]",
            row._mapping if hasattr(row, "_mapping") else row,
        )
        item_id = int(mapping["item_id"])
        prices = result.setdefault(item_id, [])
        if len(prices) >= MAX_ITEM_EXCHANGE_PRICE_ROWS:
            continue
        purchase_limit = mapping["purchase_limit"]
        currency_item_id = int(mapping["currency_item_id"])
        currency_name = str(mapping["currency_name"] or "").strip()
        prices.append(
            ItemExchangePrice(
                source_name=str(mapping["source_name"] or "兑换"),
                item_quantity=int(mapping["item_quantity"] or 1),
                currency_item_id=currency_item_id,
                currency_name=currency_name or f"道具{currency_item_id}",
                amount=int(mapping["amount"]),
                purchase_limit=(
                    int(purchase_limit) if purchase_limit is not None else None
                ),
            )
        )
    return result
