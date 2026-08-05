# SPDX-License-Identifier: MIT
"""OneBot adapter for Bilibili rich-media push delivery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.bilibili.targets import BiliPushTargets

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.delivery import MessageLimiter
    from ironsbot.integrations.onebot.delivery_port import OneBotMessageDelivery
    from ironsbot.integrations.onebot.targets import OneBotMessageTarget
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )


FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic content push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"
DYNAMIC_HISTORY_HINT = "回复“动态”查询历史动态"
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
# The first send counts toward the total. Failed rich-media delivery therefore
# receives at most two retries before a single administrator notice is sent.
FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS = 3
FULL_DYNAMIC_CONTENT_RETRY_DELAY_SECONDS = 3.0
FULL_DYNAMIC_CONTENT_FAILURE_SUBSCRIPTION_KEY = "admin_notice"
FULL_DYNAMIC_CONTENT_FAILURE_ACTION = "Bilibili dynamic content delivery failure"
DynamicLinkRenderer = Callable[[dict[str, Any], int], Any | None]
DynamicContentRenderer = Callable[[dict[str, Any], str | None], Any | None]
DynamicSummarizer = Callable[[str, int], Awaitable[str | None]]
HintAppender = Callable[[Any, str], Any]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneBotBilibiliPushSender:
    """Preserve OneBot push semantics behind the Bilibili monitor sender port."""

    delivery: OneBotMessageDelivery
    subscriptions: PushSubscriptionRepository
    render_link: DynamicLinkRenderer
    render_content: DynamicContentRenderer
    append_hint: HintAppender
    message_limiter: MessageLimiter | None = None
    summarize: DynamicSummarizer | None = None
    content_max_chars: int = 400
    summary_max_chars: int = 250
    summary_use_ai: bool = True
    can_query_history: Callable[[ConversationRef], bool] | None = None
    admin_notices: AdminNoticeService | None = None

    async def send(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
    ) -> None:
        subscription_key = bili_push_subscription_key(author_mid)
        await self._send_link_only_targets(item, pub_ts, author_mid, targets)

        full_targets = self._subscribed_full_targets(targets, subscription_key)
        if not full_targets.has_targets:
            return

        link_message = self.render_link(item, pub_ts)
        if link_message is None:
            return
        await self.delivery.broadcast(
            link_message,
            group_ids=_onebot_ids(full_targets.full_group_conversations),
            private_user_ids=_onebot_ids(full_targets.full_private_conversations),
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} link",
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            message_limiter=self._transform_target_message,
            subscription_key=subscription_key,
        )

        content = dynamic_content(item)
        content_override = await self._content_override(content)
        content_message = self.render_content(item, content_override)
        if content_message is None:
            return
        await self._send_content_with_retries(
            item,
            author_mid,
            content_message,
            full_targets,
        )

    async def _send_content_with_retries(
        self,
        item: dict[str, Any],
        author_mid: int,
        content_message: Any,
        targets: BiliPushTargets,
    ) -> None:
        remaining_group_ids = _onebot_ids(targets.full_group_conversations)
        remaining_user_ids = _onebot_ids(targets.full_private_conversations)
        for attempt in range(1, FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS + 1):
            action_name = (
                FULL_DYNAMIC_PUSH_ACTION
                if attempt == 1
                else f"{FULL_DYNAMIC_PUSH_ACTION} retry {attempt}/"
                f"{FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS}"
            )
            summary = await self.delivery.broadcast(
                content_message,
                group_ids=remaining_group_ids,
                private_user_ids=remaining_user_ids,
                action_name=action_name,
                interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            )
            remaining_group_ids = [
                target.target_id
                for target in summary.failed
                if target.target_type == "group"
            ]
            remaining_user_ids = [
                target.target_id
                for target in summary.failed
                if target.target_type == "private"
            ]
            if not remaining_group_ids and not remaining_user_ids:
                return
            if attempt < FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS:
                logger.warning(
                    "%s failed for %s group and %s private targets; retrying "
                    "attempt %s/%s",
                    FULL_DYNAMIC_PUSH_ACTION,
                    len(remaining_group_ids),
                    len(remaining_user_ids),
                    attempt + 1,
                    FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS,
                )
                await asyncio.sleep(FULL_DYNAMIC_CONTENT_RETRY_DELAY_SECONDS)

        await self._notify_content_delivery_failure(
            item,
            author_mid,
            remaining_group_ids,
            remaining_user_ids,
        )

    async def _notify_content_delivery_failure(
        self,
        item: dict[str, Any],
        author_mid: int,
        failed_group_ids: list[int],
        failed_user_ids: list[int],
    ) -> None:
        if self.admin_notices is None:
            logger.error(
                "%s exhausted %s attempts without an admin notice service: "
                "author=%s dynamic=%s groups=%s users=%s",
                FULL_DYNAMIC_PUSH_ACTION,
                FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS,
                author_mid,
                item.get("id_str", "unknown"),
                failed_group_ids,
                failed_user_ids,
            )
            return

        target_lines = [
            *(f"群：{group_id}" for group_id in failed_group_ids),
            *(f"私聊：{user_id}" for user_id in failed_user_ids),
        ]
        await self.admin_notices.send_private_to_superusers(
            "⚠️ B站动态正文/图片发送失败\n"
            f"已尝试 {FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS} 次，仍未完成。\n"
            f"UID：{author_mid}\n"
            f"动态ID：{item.get('id_str', '未知')}\n"
            f"失败目标：{'；'.join(target_lines)}\n"
            "请检查 QQ / OneBot 富媒体上传通道。",
            subscription_key=FULL_DYNAMIC_CONTENT_FAILURE_SUBSCRIPTION_KEY,
            action_name=FULL_DYNAMIC_CONTENT_FAILURE_ACTION,
        )

    async def _send_link_only_targets(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
    ) -> None:
        if (
            not targets.link_group_conversations
            and not targets.link_private_conversations
        ):
            return
        message = self.render_link(item, pub_ts)
        if message is None:
            return
        await self.delivery.broadcast(
            message,
            group_ids=_onebot_ids(targets.link_group_conversations),
            private_user_ids=_onebot_ids(targets.link_private_conversations),
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
            full_group_conversations=self.subscriptions.filter_subscribed_conversations(
                targets.full_group_conversations,
                subscription_key,
            ),
            link_group_conversations=[],
            full_private_conversations=(
                self.subscriptions.filter_subscribed_conversations(
                    targets.full_private_conversations,
                    subscription_key,
                )
            ),
            link_private_conversations=[],
        )

    def _transform_target_message(
        self,
        message: Any,
        target: OneBotMessageTarget,
    ) -> Any:
        if self.message_limiter is not None:
            message = self.message_limiter(message, target)
        if self.can_query_history is not None and self.can_query_history(
            _onebot_conversation(target)
        ):
            message = self.append_hint(message, DYNAMIC_HISTORY_HINT)
        if target.target_type != "group":
            return message
        if not self.subscriptions.mark_daily_hint_sent(
            _onebot_conversation(target),
            BILI_PUSH_ADMIN_HINT_KEY,
        ):
            return message.rstrip() if isinstance(message, str) else message
        return self.append_hint(message, BILI_PUSH_ADMIN_HINT)


def _onebot_conversation(target: OneBotMessageTarget) -> ConversationRef:
    return ConversationRef(
        platform=Platform.ONEBOT,
        kind="group" if target.target_type == "group" else "private",
        id=str(target.target_id),
    )


def _onebot_ids(conversations: list[ConversationRef]) -> list[int]:
    return [
        int(conversation.id)
        for conversation in conversations
        if (
            conversation.platform is Platform.ONEBOT
            and conversation.kind in {"private", "group"}
            and conversation.id.isdecimal()
            and int(conversation.id) > 0
        )
    ]
