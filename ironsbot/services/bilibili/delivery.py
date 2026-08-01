# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.bilibili.targets import BiliPushTargets

if TYPE_CHECKING:
    from ironsbot.core.messaging import MessageTarget
    from ironsbot.services.messaging.delivery import (
        MessageDelivery,
        MessageLimiter,
    )
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )

FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / "
    "B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
DynamicRenderMode = Literal["full", "link"]
DynamicRenderer = Callable[
    [dict[str, Any], int, DynamicRenderMode],
    Any | None,
]
DynamicSummaryRenderer = Callable[[dict[str, Any], int, str], Any | None]
DynamicSummarizer = Callable[[str, int], Awaitable[str | None]]
HintAppender = Callable[[Any, str], Any]


@dataclass(frozen=True, slots=True)
class DynamicPushDelivery:
    message: Any
    group_ids: list[int]
    private_user_ids: list[int]
    action_name: str


@dataclass(frozen=True, slots=True)
class BilibiliPushDeliveryService:
    delivery: MessageDelivery
    subscriptions: PushSubscriptionRepository
    render: DynamicRenderer
    append_hint: HintAppender
    message_limiter: MessageLimiter | None = None
    summary_renderer: DynamicSummaryRenderer | None = None
    summarize: DynamicSummarizer | None = None
    content_max_chars: int = 400
    summary_max_chars: int = 250

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
        if len(dynamic_content(item)) > self.content_max_chars:
            await self._send_long_dynamic(item, pub_ts, author_mid, targets)
            return
        for planned in self.build_deliveries(item, pub_ts, targets):
            await self._send_planned(planned, author_mid)

    async def _send_long_dynamic(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
    ) -> None:
        subscription_key = bili_push_subscription_key(author_mid)
        link_deliveries = self._mode_deliveries(
            item,
            pub_ts,
            mode="link",
            group_ids=targets.link_group_ids,
            private_user_ids=targets.link_user_ids,
            action_name=LINK_DYNAMIC_PUSH_ACTION,
        )
        for planned in link_deliveries:
            await self._send_planned(planned, author_mid)

        full_targets = self._subscribed_full_targets(targets, subscription_key)
        if not full_targets.has_targets:
            return
        notice = self._long_dynamic_notice(item, pub_ts)
        if notice is None:
            return
        await self.delivery.broadcast(
            notice,
            group_ids=full_targets.full_group_ids,
            private_user_ids=full_targets.full_user_ids,
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} notice",
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
        )

        summary = await self._summary_for(dynamic_content(item))
        message = self._summary_message(item, pub_ts, summary)
        if message is None:
            return
        await self.delivery.broadcast(
            message,
            group_ids=targets.full_group_ids,
            private_user_ids=targets.full_user_ids,
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} summary",
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            message_limiter=self._transform_target_message,
            subscription_key=subscription_key,
        )

    async def _send_planned(
        self,
        planned: DynamicPushDelivery,
        author_mid: int,
    ) -> None:
        await self.delivery.broadcast(
            planned.message,
            group_ids=planned.group_ids,
            private_user_ids=planned.private_user_ids,
            action_name=planned.action_name,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            message_limiter=self._transform_target_message,
            subscription_key=bili_push_subscription_key(author_mid),
        )

    def _subscribed_full_targets(
        self,
        targets: BiliPushTargets,
        subscription_key: str,
    ) -> BiliPushTargets:
        return BiliPushTargets(
            full_group_ids=self.subscriptions.filter_subscribed_group_ids(
                targets.full_group_ids,
                subscription_key,
            ),
            link_group_ids=[],
            full_user_ids=self.subscriptions.filter_subscribed_user_ids(
                targets.full_user_ids,
                subscription_key,
            ),
            link_user_ids=[],
        )

    def _long_dynamic_notice(
        self,
        item: dict[str, Any],
        pub_ts: int,
    ) -> Any | None:
        message = self.render(item, pub_ts, "link")
        if message is None:
            return None
        notice = (
            f"\n原文超过 {self.content_max_chars} 字，下一条发送摘要。"
        )
        if isinstance(message, str):
            return f"{message.rstrip()}{notice}"
        return message + notice

    async def _summary_for(self, content: str) -> str:
        summary = (
            await self.summarize(content, self.summary_max_chars)
            if self.summarize is not None
            else None
        )
        return summary or content[: self.summary_max_chars].rstrip()

    def _summary_message(
        self,
        item: dict[str, Any],
        pub_ts: int,
        summary: str,
    ) -> Any | None:
        if self.summary_renderer is not None:
            return self.summary_renderer(item, pub_ts, summary)
        return summary

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
        if not group_ids and not private_user_ids:
            return []
        message = self.render(item, pub_ts, mode)
        if message is None:
            return []
        return [
            DynamicPushDelivery(
                message=message,
                group_ids=group_ids,
                private_user_ids=private_user_ids,
                action_name=action_name,
            )
        ]

    def _transform_target_message(
        self,
        message: Any,
        target: MessageTarget,
    ) -> Any:
        if self.message_limiter is not None:
            message = self.message_limiter(message, target)
        if target.target_type != "group":
            return message
        group_id = target.target_id
        if not self.subscriptions.mark_daily_hint_sent(
            "group",
            group_id,
            BILI_PUSH_ADMIN_HINT_KEY,
        ):
            return message.rstrip() if isinstance(message, str) else message
        return self.append_hint(message, BILI_PUSH_ADMIN_HINT)
