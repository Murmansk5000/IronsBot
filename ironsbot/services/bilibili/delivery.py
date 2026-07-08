from dataclasses import dataclass
from typing import Any, Protocol

from nonebot.adapters.onebot.v11 import Message

from ironsbot.services.bilibili.parser import parse_single_item
from ironsbot.shared.promotions import (
    append_fire_manual_ad_message,
    split_fire_manual_ad_group_ids,
)

FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = "\n\n管理：B站账号 / B站推送模式"


class HasDynamicPushTargets(Protocol):
    full_group_ids: list[int]
    link_group_ids: list[int]
    full_user_ids: list[int]
    link_user_ids: list[int]


@dataclass(frozen=True, slots=True)
class DynamicPushDelivery:
    message: Message
    group_ids: list[int]
    private_user_ids: list[int]
    action_name: str


def build_dynamic_push_deliveries(
    item: dict[str, Any],
    pub_ts: int,
    targets: HasDynamicPushTargets,
) -> list[DynamicPushDelivery]:
    deliveries: list[DynamicPushDelivery] = []

    if targets.full_group_ids or targets.full_user_ids:
        full_message = parse_single_item(item, pub_ts, mode="full")
        if full_message:
            deliveries.extend(
                _build_delivery_variants(
                    full_message,
                    group_ids=targets.full_group_ids,
                    private_user_ids=targets.full_user_ids,
                    action_name=FULL_DYNAMIC_PUSH_ACTION,
                )
            )

    if targets.link_group_ids or targets.link_user_ids:
        link_message = parse_single_item(item, pub_ts, mode="link")
        if link_message:
            deliveries.extend(
                _build_delivery_variants(
                    link_message,
                    group_ids=targets.link_group_ids,
                    private_user_ids=targets.link_user_ids,
                    action_name=LINK_DYNAMIC_PUSH_ACTION,
                )
            )

    return deliveries


def _build_delivery_variants(
    message: Message,
    *,
    group_ids: list[int],
    private_user_ids: list[int],
    action_name: str,
) -> list[DynamicPushDelivery]:
    ad_group_ids, plain_group_ids = split_fire_manual_ad_group_ids(group_ids)
    deliveries: list[DynamicPushDelivery] = []

    if ad_group_ids:
        deliveries.append(
            DynamicPushDelivery(
                message=_append_admin_hint(
                    append_fire_manual_ad_message(message.copy())
                ),
                group_ids=ad_group_ids,
                private_user_ids=[],
                action_name=action_name,
            )
        )

    if private_user_ids:
        deliveries.append(
            DynamicPushDelivery(
                message=append_fire_manual_ad_message(message.copy()),
                group_ids=[],
                private_user_ids=private_user_ids,
                action_name=action_name,
            )
        )

    if plain_group_ids:
        deliveries.append(
            DynamicPushDelivery(
                message=_append_admin_hint(message.copy()),
                group_ids=plain_group_ids,
                private_user_ids=[],
                action_name=action_name,
            )
        )

    return deliveries


def _append_admin_hint(message: Message) -> Message:
    message += BILI_PUSH_ADMIN_HINT
    return message
