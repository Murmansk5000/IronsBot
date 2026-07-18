from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.config.loader import get_app_config
from ironsbot.services.bilibili.parser import parse_single_item
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore
from ironsbot.shared.messaging.push_subscriptions import append_text_hint
from ironsbot.shared.promotions import (
    append_fire_manual_ad_message,
    split_fire_manual_ad_group_ids,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.shared.features import FeatureService

FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / B站推送模式 <账号别名> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"


class HasDynamicPushTargets(Protocol):
    @property
    def full_group_ids(self) -> list[int]: ...

    @property
    def link_group_ids(self) -> list[int]: ...

    @property
    def full_user_ids(self) -> list[int]: ...

    @property
    def link_user_ids(self) -> list[int]: ...


@dataclass(frozen=True, slots=True)
class DynamicPushDelivery:
    message: Message
    group_ids: list[int]
    private_user_ids: list[int]
    action_name: str


def build_dynamic_push_deliveries(
    features: FeatureService,
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
                    features,
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
                    features,
                    link_message,
                    group_ids=targets.link_group_ids,
                    private_user_ids=targets.link_user_ids,
                    action_name=LINK_DYNAMIC_PUSH_ACTION,
                )
            )

    return deliveries


def _build_delivery_variants(
    features: FeatureService,
    message: Message,
    *,
    group_ids: list[int],
    private_user_ids: list[int],
    action_name: str,
) -> list[DynamicPushDelivery]:
    ad_group_ids, plain_group_ids = split_fire_manual_ad_group_ids(
        features,
        group_ids,
    )
    deliveries: list[DynamicPushDelivery] = []

    if ad_group_ids:
        deliveries.append(
            DynamicPushDelivery(
                message=append_fire_manual_ad_message(message.copy()),
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
                message=message.copy(),
                group_ids=plain_group_ids,
                private_user_ids=[],
                action_name=action_name,
            )
        )

    return deliveries


def append_bili_admin_hint_for_group(
    message: str | Message,
    group_id: int | None,
) -> str | Message:
    if group_id is None:
        return message

    config = get_app_config().message.push_unsubscribe
    store = PushUnsubscribeStore(config.data_path)
    if not store.mark_daily_hint_sent("group", group_id, BILI_PUSH_ADMIN_HINT_KEY):
        return message.rstrip() if isinstance(message, str) else message

    return append_text_hint(message, BILI_PUSH_ADMIN_HINT)
