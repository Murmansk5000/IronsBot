# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

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
    ticket_name: str | None = None
    ticket_diamonds: int | None = None


def skin_ticket_name(price: SkinStorePrice) -> str:
    """Use the published item name without guessing a coupon identity."""
    if name := (price.ticket_name or "").strip():
        return name
    return f"券道具{price.ticket_id}" if price.ticket_id > 0 else "优惠券"


def skin_ticket_discount(price: SkinStorePrice) -> int | None:
    """Apply only the positive per-ticket value published by SeerAPI."""
    if (
        price.ticket_id <= 0
        or price.ticket_num <= 0
        or price.ticket_diamonds is None
        or price.ticket_diamonds <= 0
    ):
        return None
    return price.ticket_num * price.ticket_diamonds


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


@dataclass(frozen=True, slots=True)
class SkinModelPrice:
    card_price: int | None
    diamond_price: int | None
    skinhouse_price: int | None
    discounted_skinhouse_price: int | None
    ticket_num: int | None


def merge_skin_price_facts(
    *,
    skin_id: int,
    resource_id: int,
    model: SkinModelPrice,
    shop: SkinShopPrice | None,
    stores: list[SkinStorePrice],
) -> tuple[SkinShopPrice, list[SkinStorePrice]]:
    """Supplement missing published facts without creating another storefront."""
    shop = shop or SkinShopPrice(skin_id, resource_id, 0, 0, 0)
    shop = replace(
        shop,
        card_price=shop.card_price if shop.card_price > 0 else model.card_price or 0,
        diamond_price=(
            shop.diamond_price if shop.diamond_price > 0 else model.diamond_price or 0
        ),
    )
    # The model has no pool identity; multiple detailed offers cannot be matched.
    if len(stores) > 1:
        return shop, stores
    original = model.skinhouse_price or 0
    model_price = model.discounted_skinhouse_price or original
    if not stores and model_price <= 0:
        return shop, stores
    store = stores[0] if stores else SkinStorePrice(skin_id, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    store = replace(
        store,
        price=store.price if store.price > 0 else model_price,
        original_price=store.original_price if store.original_price > 0 else original,
        ticket_num=store.ticket_num if store.ticket_num > 0 else model.ticket_num or 0,
    )
    return shop, [store]


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
        parts.append(format_skin_store_amount(price))
    if price.selected_price > 0 and price.selected_price != price.price:
        parts.append(f"自选{price.selected_price}钻")
    if price.ticket_num > 0 and price.price > 0:
        _, ticket_text = skin_ticket_summary(price)
        if ticket_text:
            parts.append(ticket_text)

    return "幸运橱窗：" + "；".join(parts)


def format_lucky_window_price_lines(
    price: SkinStorePrice | None,
) -> tuple[str, ...]:
    """Format one active lucky-window offer without presentation assets."""

    if price is None or price.price <= 0:
        return ("橱窗价格暂未获取",)
    first = f"橱窗价：{format_skin_store_amount(price)}"
    _, ticket_text = skin_ticket_summary(price)
    return (first, ticket_text) if ticket_text else (first,)


def format_skin_store_amount(price: SkinStorePrice) -> str:
    text = f"{price.price}钻"
    if price.original_price > 0 and price.original_price != price.price:
        text += f"（原价{price.original_price}钻）"
    return text


def skin_ticket_summary(
    price: SkinStorePrice, *, quantity_prefix: str = "最多用"
) -> tuple[int | None, str | None]:
    """Calculate the payment and coupon wording once for text and image views."""
    if price.ticket_num <= 0:
        return None, None
    discount = skin_ticket_discount(price)
    minimum = (
        max(price.price - discount, 0)
        if price.price > 0 and discount is not None
        else None
    )
    text = f"{quantity_prefix}{price.ticket_num}张{skin_ticket_name(price)}"
    if discount is None:
        return minimum, text
    if discount < price.price:
        return minimum, f"{text}，最低{minimum}钻"
    return minimum, f"{text}，可抵扣{discount}钻"


def _dedupe_lines(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result
