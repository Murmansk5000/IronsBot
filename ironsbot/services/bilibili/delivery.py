# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.bilibili import SeerDynamicCategory, truncate_bilibili_text
from ironsbot.core.onebot_group_identity import (
    format_group_label,
    resolve_group_name,
)
from ironsbot.services.bilibili.parser import dynamic_content
from ironsbot.services.bilibili.preferences import (
    BiliPushMedia,
    bili_push_media_subscription_key,
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.targets import BiliPushTargets

if TYPE_CHECKING:
    from ironsbot.core.messaging import MessageTarget
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.delivery import (
        MessageDelivery,
        MessageLimiter,
    )
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )


FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic content push"
FULL_DYNAMIC_IMAGE_PUSH_ACTION = "Bilibili dynamic image push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"
DYNAMIC_HISTORY_HINT = "回复“动态”查询历史动态"
# The first send counts toward the total.  Failed rich-media delivery therefore
# receives at most two retries before a single administrator notice is sent.
FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS = 3
FULL_DYNAMIC_CONTENT_RETRY_DELAY_SECONDS = 3.0
FULL_DYNAMIC_CONTENT_FAILURE_SUBSCRIPTION_KEY = "admin_notice"
FULL_DYNAMIC_CONTENT_FAILURE_ACTION = "Bilibili dynamic content delivery failure"
BILIBILI_SUMMARY_FAILURE_SUBSCRIPTION_KEY = "admin_notice"
BILIBILI_SUMMARY_FAILURE_ACTION = "Bilibili dynamic summary failure"
BILIBILI_SUMMARY_MAX_ATTEMPTS = 3
SUMMARY_FAILURE_FALLBACK_HINT = "（摘要生成失败，完整内容请见传送门）"
DynamicLinkRenderer = Callable[[dict[str, Any], int], Any | None]
DynamicContentRenderer = Callable[[dict[str, Any], str | None], Any | None]
DynamicImageRenderer = Callable[[dict[str, Any]], Any | None]


class DynamicSummarizer(Protocol):
    async def __call__(
        self,
        text: str,
        *,
        max_chars: int,
    ) -> str | None: ...


HintAppender = Callable[[Any, str], Any]
DynamicLinkTagger = Callable[[int, tuple[SeerDynamicCategory, ...]], str | None]
logger = logging.getLogger(__name__)


def _summary_failure_fallback(content: str, max_chars: int) -> str:
    if max_chars <= len(SUMMARY_FAILURE_FALLBACK_HINT):
        return truncate_bilibili_text(content, max_chars)
    excerpt_limit = max_chars - len(SUMMARY_FAILURE_FALLBACK_HINT) - 1
    excerpt = truncate_bilibili_text(content, excerpt_limit)
    return f"{excerpt}\n{SUMMARY_FAILURE_FALLBACK_HINT}"


def _valid_summary(summary: str, max_chars: int) -> str | None:
    """Accept only a complete model response that fits the configured limit."""

    candidate = summary.strip()
    return candidate if candidate and len(candidate) <= max_chars else None


@dataclass(frozen=True, slots=True)
class BilibiliPushDeliveryService:
    delivery: MessageDelivery
    subscriptions: PushSubscriptionRepository
    render_link: DynamicLinkRenderer
    render_content: DynamicContentRenderer
    append_hint: HintAppender
    message_limiter: MessageLimiter | None = None
    summarize: DynamicSummarizer | None = None
    content_max_chars: int = 800
    summary_max_chars: int = 500
    summary_use_ai: bool = True
    can_query_history: Callable[[MessageTarget], bool] | None = None
    admin_notices: AdminNoticeService | None = None
    link_tag_for: DynamicLinkTagger | None = None
    prepend_link_tag: HintAppender | None = None
    render_images: DynamicImageRenderer | None = None
    media_preferences_uid: int | None = None

    async def send(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
        categories: tuple[SeerDynamicCategory, ...] = (),
    ) -> None:
        subscription_key = bili_push_subscription_key(author_mid)
        await self._send_link_only_targets(
            item,
            pub_ts,
            author_mid,
            targets,
            categories,
        )

        full_targets = self._subscribed_full_targets(targets, subscription_key)
        if not full_targets.has_targets:
            return

        content = dynamic_content(item)
        text_targets = self._media_targets(full_targets, author_mid, "text")
        content_message = None
        if content and text_targets.has_targets:
            content_override = await self._content_override(
                item,
                author_mid,
                content,
            )
            content_message = self.render_content(item, content_override)

        image_targets = self._media_targets(full_targets, author_mid, "image")
        image_message = (
            self.render_images(item) if self.render_images is not None else None
        )
        if image_message is None:
            image_targets = BiliPushTargets([], [], [], [])

        visible_targets = self._combined_targets(
            full_targets,
            text_targets,
            image_targets,
        )
        if not visible_targets.has_targets:
            return

        link_message = self._render_link(item, pub_ts, author_mid, categories)
        if link_message is None:
            return
        await self.delivery.broadcast(
            link_message,
            group_ids=visible_targets.full_group_ids,
            private_user_ids=visible_targets.full_user_ids,
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} link",
            message_limiter=self._transform_target_message,
            subscription_key=subscription_key,
        )

        if content_message is not None:
            await self.delivery.broadcast(
                content_message,
                group_ids=text_targets.full_group_ids,
                private_user_ids=text_targets.full_user_ids,
                action_name=FULL_DYNAMIC_PUSH_ACTION,
                subscription_key=subscription_key,
            )

        if image_message is not None:
            await self._send_images_with_retries(
                item,
                author_mid,
                image_message,
                image_targets,
                subscription_key=subscription_key,
            )

    async def _send_images_with_retries(
        self,
        item: dict[str, Any],
        author_mid: int,
        content_message: Any,
        targets: BiliPushTargets,
        *,
        subscription_key: str,
    ) -> None:
        remaining_group_ids = targets.full_group_ids
        remaining_user_ids = targets.full_user_ids
        for attempt in range(1, FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS + 1):
            action_name = (
                FULL_DYNAMIC_IMAGE_PUSH_ACTION
                if attempt == 1
                else f"{FULL_DYNAMIC_IMAGE_PUSH_ACTION} retry {attempt}/"
                f"{FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS}"
            )
            summary = await self.delivery.broadcast(
                content_message,
                group_ids=remaining_group_ids,
                private_user_ids=remaining_user_ids,
                action_name=action_name,
                subscription_key=subscription_key,
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
                    FULL_DYNAMIC_IMAGE_PUSH_ACTION,
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

        default_bot = getattr(self.delivery, "default_bot", None)
        bot = default_bot() if callable(default_bot) else None
        group_labels = await asyncio.gather(
            *(resolve_group_name(bot, group_id) for group_id in failed_group_ids)
        )
        target_lines = [
            *(
                f"群：{format_group_label(group_id, group_name)}"
                for group_id, group_name in zip(
                    failed_group_ids,
                    group_labels,
                    strict=True,
                )
            ),
            *(f"私聊：{user_id}" for user_id in failed_user_ids),
        ]
        await self.admin_notices.send_private_to_superusers(
            "⚠️ B站动态图片发送失败\n"
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
        categories: tuple[SeerDynamicCategory, ...],
    ) -> None:
        if not targets.link_group_ids and not targets.link_user_ids:
            return
        message = self._render_link(item, pub_ts, author_mid, categories)
        if message is None:
            return
        await self.delivery.broadcast(
            message,
            group_ids=targets.link_group_ids,
            private_user_ids=targets.link_user_ids,
            action_name=LINK_DYNAMIC_PUSH_ACTION,
            message_limiter=self._transform_target_message,
            subscription_key=bili_push_subscription_key(author_mid),
        )

    def _render_link(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        categories: tuple[SeerDynamicCategory, ...],
    ) -> Any | None:
        message = self.render_link(item, pub_ts)
        if (
            message is None
            or self.link_tag_for is None
            or self.prepend_link_tag is None
        ):
            return message
        tag = self.link_tag_for(author_mid, categories)
        return self.prepend_link_tag(message, tag) if tag else message

    async def _content_override(
        self,
        item: dict[str, Any],
        author_mid: int,
        content: str,
    ) -> str | None:
        if len(content) <= self.content_max_chars:
            return None
        summary: str | None = None
        failure_reason: str | None = None
        if self.summary_use_ai and self.summarize is not None:
            for attempt in range(1, BILIBILI_SUMMARY_MAX_ATTEMPTS + 1):
                try:
                    candidate = await self.summarize(
                        content,
                        max_chars=self.summary_max_chars,
                    )
                except Exception as error:  # noqa: BLE001 - optional summary retry
                    failure_reason = f"调用异常：{type(error).__name__}"
                    logger.warning(
                        "Bilibili dynamic summary attempt failed: attempt=%s/%s "
                        "error=%s",
                        attempt,
                        BILIBILI_SUMMARY_MAX_ATTEMPTS,
                        type(error).__name__,
                    )
                    continue
                if (
                    candidate is not None
                    and (
                        summary := _valid_summary(
                            candidate,
                            self.summary_max_chars,
                        )
                    )
                    is not None
                ):
                    failure_reason = None
                    break
                failure_reason = (
                    "AI 未返回有效摘要"
                    if candidate is None or not candidate.strip()
                    else (f"AI 摘要超过 {self.summary_max_chars} 字（第 {attempt} 次）")
                )
                logger.warning(
                    "Bilibili dynamic summary rejected: attempt=%s/%s reason=%s",
                    attempt,
                    BILIBILI_SUMMARY_MAX_ATTEMPTS,
                    failure_reason,
                )
        if failure_reason is not None:
            await self._notify_summary_failure(
                item,
                author_mid,
                failure_reason,
            )
        if summary is not None:
            return summary
        return _summary_failure_fallback(content, self.summary_max_chars)

    async def _notify_summary_failure(
        self,
        item: dict[str, Any],
        author_mid: int,
        reason: str,
    ) -> None:
        if self.admin_notices is None:
            logger.warning(
                "Bilibili dynamic summary failed without an admin notice service: "
                "author=%s dynamic=%s reason=%s",
                author_mid,
                item.get("id_str", "unknown"),
                reason,
            )
            return

        try:
            await self.admin_notices.send_private_to_superusers(
                "⚠️ B站动态 AI 摘要失败\n"
                f"UID：{author_mid}\n"
                f"动态ID：{item.get('id_str', '未知')}\n"
                f"原因：{reason}\n"
                f"已降级发送不超过 {self.summary_max_chars} 字的原文节选。",
                subscription_key=BILIBILI_SUMMARY_FAILURE_SUBSCRIPTION_KEY,
                action_name=BILIBILI_SUMMARY_FAILURE_ACTION,
            )
        except Exception:
            # This alert must not block marking the dynamic as delivered.
            logger.exception("failed to send Bilibili dynamic summary failure notice")

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

    def _media_targets(
        self,
        targets: BiliPushTargets,
        author_mid: int,
        media: BiliPushMedia,
    ) -> BiliPushTargets:
        if author_mid != self.media_preferences_uid:
            return targets
        subscription_key = bili_push_media_subscription_key(
            author_mid,
            media,
        )
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

    @staticmethod
    def _combined_targets(
        available_targets: BiliPushTargets,
        *targets: BiliPushTargets,
    ) -> BiliPushTargets:
        group_ids = {
            group_id
            for targets_item in targets
            for group_id in targets_item.full_group_ids
        }
        user_ids = {
            user_id
            for targets_item in targets
            for user_id in targets_item.full_user_ids
        }
        return BiliPushTargets(
            full_group_ids=[
                group_id
                for group_id in available_targets.full_group_ids
                if group_id in group_ids
            ],
            link_group_ids=[],
            full_user_ids=[
                user_id
                for user_id in available_targets.full_user_ids
                if user_id in user_ids
            ],
            link_user_ids=[],
        )

    def _transform_target_message(
        self,
        message: Any,
        target: MessageTarget,
    ) -> Any:
        if self.message_limiter is not None:
            message = self.message_limiter(message, target)
        if self.can_query_history is not None and self.can_query_history(target):
            message = self.append_hint(message, DYNAMIC_HISTORY_HINT)
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
