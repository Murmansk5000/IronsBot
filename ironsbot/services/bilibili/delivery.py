# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.messaging.promotions import split_fire_manual_ad_group_ids

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.bilibili.targets import BiliPushTargets
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )

FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / B站推送模式 <账号别名> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
DynamicRenderMode = Literal["full", "link"]
DynamicRenderer = Callable[
    [dict[str, Any], int, DynamicRenderMode],
    Any | None,
]
MessageTransform = Callable[[Any], Any]
HintAppender = Callable[[Any, str], Any]


@dataclass(frozen=True, slots=True)
class DynamicPushDelivery:
    message: Any
    group_ids: list[int]
    private_user_ids: list[int]
    action_name: str


@dataclass(frozen=True, slots=True)
class BilibiliPushDeliveryService:
    features: FeatureService
    delivery: MessageDelivery
    subscriptions: PushSubscriptionRepository
    render: DynamicRenderer
    append_promotion: MessageTransform
    append_hint: HintAppender

    def build_deliveries(
        self,
        item: dict[str, Any],
        pub_ts: int,
        targets: BiliPushTargets,
    ) -> list[DynamicPushDelivery]:
        deliveries: list[DynamicPushDelivery] = []
        deliveries.extend(
            self._mode_deliveries(
                item,
                pub_ts,
                mode="full",
                group_ids=targets.full_group_ids,
                private_user_ids=targets.full_user_ids,
                action_name=FULL_DYNAMIC_PUSH_ACTION,
            )
        )
        deliveries.extend(
            self._mode_deliveries(
                item,
                pub_ts,
                mode="link",
                group_ids=targets.link_group_ids,
                private_user_ids=targets.link_user_ids,
                action_name=LINK_DYNAMIC_PUSH_ACTION,
            )
        )
        return deliveries

    async def send(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
    ) -> None:
        for planned in self.build_deliveries(item, pub_ts, targets):
            await self.delivery.broadcast(
                planned.message,
                group_ids=planned.group_ids,
                private_user_ids=planned.private_user_ids,
                action_name=planned.action_name,
                interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
                message_limiter=self._append_admin_hint,
                subscription_key=bili_push_subscription_key(author_mid),
            )

    def _mode_deliveries(  # noqa: PLR0913 - explicit delivery dimensions
        self,
        item: dict[str, Any],
        pub_ts: int,
        *,
        mode: DynamicRenderMode,
        group_ids: list[int],
        private_user_ids: list[int],
        action_name: str,
    ) -> list[DynamicPushDelivery]:
        promoted_groups, plain_groups = split_fire_manual_ad_group_ids(
            self.features,
            group_ids,
        )
        variants = (
            (promoted_groups, [], True),
            ([], private_user_ids, True),
            (plain_groups, [], False),
        )
        deliveries: list[DynamicPushDelivery] = []
        for variant_groups, variant_users, promoted in variants:
            if not variant_groups and not variant_users:
                continue
            message = self.render(item, pub_ts, mode)
            if message is None:
                continue
            if promoted:
                message = self.append_promotion(message)
            deliveries.append(
                DynamicPushDelivery(
                    message=message,
                    group_ids=variant_groups,
                    private_user_ids=variant_users,
                    action_name=action_name,
                )
            )
        return deliveries

    def _append_admin_hint(self, message: Any, group_id: int | None) -> Any:
        if group_id is None:
            return message
        if not self.subscriptions.mark_daily_hint_sent(
            "group",
            group_id,
            BILI_PUSH_ADMIN_HINT_KEY,
        ):
            return message.rstrip() if isinstance(message, str) else message
        return self.append_hint(message, BILI_PUSH_ADMIN_HINT)
