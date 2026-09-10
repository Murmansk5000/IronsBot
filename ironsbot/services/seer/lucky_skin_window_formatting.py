# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.services.seer.skin_price import FASHION_TICKET_VALUE, SkinStorePrice


def format_offer_price(price: SkinStorePrice) -> tuple[str, ...]:
    if price.price <= 0:
        return ("   橱窗价格数据异常",)

    price_text = f"   橱窗价：{price.price}钻"
    if price.original_price > 0 and price.original_price != price.price:
        price_text += f"（原价{price.original_price}钻）"
    if price.ticket_num <= 0:
        return (price_text,)

    ticket_discount = price.ticket_num * FASHION_TICKET_VALUE
    if ticket_discount < price.price:
        minimum = price.price - ticket_discount
        ticket_text = f"   最多用{price.ticket_num}张风尚券，最低{minimum}钻"
    else:
        ticket_text = f"   最多用{price.ticket_num}张风尚券，可抵扣{ticket_discount}钻"
    return price_text, ticket_text
