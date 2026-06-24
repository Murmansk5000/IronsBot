from dataclasses import dataclass
from typing import Any, Protocol

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.services.bilibili.parser import parse_single_item
from ironsbot.shared.promotions import FIRE_MANUAL_LINK_MESSAGE, FIRE_MANUAL_URL

FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"


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


def append_fire_manual_ad_message(message: Message) -> Message:
    if FIRE_MANUAL_URL in str(message):
        return message
    message += MessageSegment.text(f"\n\n{FIRE_MANUAL_LINK_MESSAGE}")
    return message


def build_dynamic_push_deliveries(
    item: dict[str, Any],
    pub_ts: int,
    targets: HasDynamicPushTargets,
) -> list[DynamicPushDelivery]:
    deliveries: list[DynamicPushDelivery] = []

    if targets.full_group_ids or targets.full_user_ids:
        full_message = parse_single_item(item, pub_ts, mode="full")
        if full_message:
            full_message = append_fire_manual_ad_message(full_message)
            deliveries.append(
                DynamicPushDelivery(
                    message=full_message,
                    group_ids=targets.full_group_ids,
                    private_user_ids=targets.full_user_ids,
                    action_name=FULL_DYNAMIC_PUSH_ACTION,
                )
            )

    if targets.link_group_ids or targets.link_user_ids:
        link_message = parse_single_item(item, pub_ts, mode="link")
        if link_message:
            link_message = append_fire_manual_ad_message(link_message)
            deliveries.append(
                DynamicPushDelivery(
                    message=link_message,
                    group_ids=targets.link_group_ids,
                    private_user_ids=targets.link_user_ids,
                    action_name=LINK_DYNAMIC_PUSH_ACTION,
                )
            )

    return deliveries
