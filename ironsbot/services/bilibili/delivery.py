# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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


FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic content push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / "
    "B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
DynamicLinkRenderer = Callable[[dict[str, Any]], Any | None]
DynamicContentRenderer = Callable[[dict[str, Any], str | None], Any | None]
DynamicSummarizer = Callable[[str, int], Awaitable[str | None]]
HintAppender = Callable[[Any, str], Any]


@dataclass(frozen=True, slots=True)
class BilibiliPushDeliveryService:
    delivery: MessageDelivery
    subscriptions: PushSubscriptionRepository
    render_link: DynamicLinkRenderer
    render_content: DynamicContentRenderer
    append_hint: HintAppender
    message_limiter: MessageLimiter | None = None
    summarize: DynamicSummarizer | None = None
    content_max_chars: int = 400
    summary_max_chars: int = 250
    summary_use_ai: bool = True

    async def send(
        self,
        item: dict[str, Any],
        _pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
    ) -> None:
        subscription_key = bili_push_subscription_key(author_mid)
        await self._send_link_only_targets(item, author_mid, targets)

        full_targets = self._subscribed_full_targets(targets, subscription_key)
        if not full_targets.has_targets:
            return

        link_message = self.render_link(item)
        if link_message is None:
            return
        await self.delivery.broadcast(
            link_message,
            group_ids=full_targets.full_group_ids,
            private_user_ids=full_targets.full_user_ids,
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} link",
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
        )

        content = dynamic_content(item)
        content_override = await self._content_override(content)
        content_message = self.render_content(item, content_override)
        if content_message is None:
            return
        await self.delivery.broadcast(
            content_message,
            group_ids=targets.full_group_ids,
            private_user_ids=targets.full_user_ids,
            action_name=FULL_DYNAMIC_PUSH_ACTION,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            message_limiter=self._transform_target_message,
            subscription_key=subscription_key,
        )

    async def _send_link_only_targets(
        self,
        item: dict[str, Any],
        author_mid: int,
        targets: BiliPushTargets,
    ) -> None:
        if not targets.link_group_ids and not targets.link_user_ids:
            return
        message = self.render_link(item)
        if message is None:
            return
        await self.delivery.broadcast(
            message,
            group_ids=targets.link_group_ids,
            private_user_ids=targets.link_user_ids,
            action_name=LINK_DYNAMIC_PUSH_ACTION,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            message_limiter=self._transform_target_message,
            subscription_key=bili_push_subscription_key(author_mid),
        )

    async def _content_override(self, content: str) -> str | None:
        if len(content) <= self.content_max_chars:
            return None
        summary = (
            await self.summarize(content, self.summary_max_chars)
            if self.summary_use_ai and self.summarize is not None
            else None
        )
        return summary or content[: self.summary_max_chars].rstrip()

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
