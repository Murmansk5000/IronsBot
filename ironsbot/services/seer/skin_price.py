# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

FASHION_TICKET_VALUE = 10
MAX_PRICE_ROWS = 3


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


def format_skin_price_lines(
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
