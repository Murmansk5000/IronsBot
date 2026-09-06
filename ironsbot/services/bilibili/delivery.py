# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.bilibili import SeerDynamicCategory, truncate_bilibili_text
from ironsbot.core.messaging import MessageTarget
from ironsbot.core.onebot_group_identity import (
    format_group_label,
    resolve_group_name,
)
from ironsbot.services.bilibili.parser import dynamic_content, dynamic_id
from ironsbot.services.bilibili.preferences import (
    BiliPushMedia,
    bili_push_media_subscription_key,
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.targets import BiliPushTargets

if TYPE_CHECKING:
    from ironsbot.services.bilibili.dynamic_history import BiliDynamicHistoryStore
    from ironsbot.services.bilibili.image_delivery_retries import (
        BiliImageDeliveryRetryStore,
    )
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
SEER_DYNAMIC_TAG_UNSUBSCRIBE_HINT = "发送 TD 可按标签退订赛尔号动态。"
SEER_DYNAMIC_TAG_UNSUBSCRIBE_HINT_KEY = "seer_dynamic_tag_unsubscribe_hint"
FULL_DYNAMIC_CONTENT_FAILURE_SUBSCRIPTION_KEY = "admin_notice"
FULL_DYNAMIC_CONTENT_FAILURE_ACTION = "Bilibili dynamic content delivery failure"
BILIBILI_SUMMARY_FAILURE_SUBSCRIPTION_KEY = "admin_notice"
BILIBILI_SUMMARY_FAILURE_ACTION = "Bilibili dynamic summary failure"
BILIBILI_SUMMARY_MAX_ATTEMPTS = 3
SUMMARY_FAILURE_FALLBACK_HINT = "（摘要生成失败，完整内容请见传送门）"
DynamicLinkRenderer = Callable[[dict[str, Any], int], Any | None]
DynamicContentRenderer = Callable[[dict[str, Any], str | None], Any | None]
DynamicImageRenderer = Callable[
    [dict[str, Any]],
    Any | Awaitable[Any | None],
]


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


async def _render_dynamic_images(
    renderer: DynamicImageRenderer | None,
    item: dict[str, Any],
) -> Any | None:
    if renderer is None:
        return None
    rendered = renderer(item)
    return await rendered if isawaitable(rendered) else rendered


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
    history: BiliDynamicHistoryStore | None = None
    image_delivery_retries: BiliImageDeliveryRetryStore | None = None
    image_retry_max_attempts: int = 3
    retry_targets_for_uid: Callable[[int], BiliPushTargets] | None = None

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
        image_message = await _render_dynamic_images(self.render_images, item)
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
            message_limiter=partial(
                self._transform_target_message,
                author_mid=author_mid,
            ),
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
            summary = await self.delivery.broadcast(
                image_message,
                group_ids=image_targets.full_group_ids,
                private_user_ids=image_targets.full_user_ids,
                action_name=FULL_DYNAMIC_IMAGE_PUSH_ACTION,
                subscription_key=subscription_key,
                # QQ may deliver rich media after its OneBot request times out.
                # Do not turn an ambiguous failure into duplicate images.
                retry_failed_targets=False,
            )
            if summary.failed:
                uncertain_targets = set(summary.uncertain)
                self._record_image_delivery_failures(
                    item,
                    [
                        target
                        for target in summary.failed
                        if target not in uncertain_targets
                    ],
                )
                if self.image_delivery_retries is None:
                    await self._notify_content_delivery_failure(
                        item,
                        author_mid,
                        [
                            target.target_id
                            for target in summary.failed
                            if target.target_type == "group"
                        ],
                        [
                            target.target_id
                            for target in summary.failed
                            if target.target_type == "private"
                        ],
                    )
            self._log_uncertain_image_delivery(
                dynamic_id(item),
                summary.uncertain,
                phase="initial",
            )

    async def retry_failed_images(self) -> None:
        """Retry only persisted image targets left unconfirmed by earlier pushes."""

        if (
            self.history is None
            or self.image_delivery_retries is None
            or self.retry_targets_for_uid is None
        ):
            return
        retries_by_dynamic: dict[str, list[tuple[MessageTarget, int]]] = {}
        for retry in self.image_delivery_retries.list_pending():
            retries_by_dynamic.setdefault(retry.dynamic_id, []).append(
                (retry.target, retry.attempts)
            )

        for item_id, retries in retries_by_dynamic.items():
            record = self.history.get(item_id)
            if record is None:
                self.image_delivery_retries.resolve(
                    item_id,
                    [target for target, _attempts in retries],
                )
                continue
            image_message = await _render_dynamic_images(
                self.render_images,
                record.item,
            )
            if image_message is None:
                self.image_delivery_retries.resolve(
                    item_id,
                    [target for target, _attempts in retries],
                )
                continue

            retry_targets = self._retry_image_targets(record.uid, retries)
            current_targets = {target for target, _attempts in retries}
            retained_targets = {
                MessageTarget("group", group_id)
                for group_id in retry_targets.full_group_ids
            } | {
                MessageTarget("private", user_id)
                for user_id in retry_targets.full_user_ids
            }
            self.image_delivery_retries.resolve(
                item_id,
                current_targets - retained_targets,
            )
            if not retained_targets:
                continue

            summary = await self.delivery.broadcast(
                image_message,
                group_ids=retry_targets.full_group_ids,
                private_user_ids=retry_targets.full_user_ids,
                action_name=f"{FULL_DYNAMIC_IMAGE_PUSH_ACTION} retry",
                subscription_key=bili_push_subscription_key(record.uid),
                retry_failed_targets=False,
            )
            self.image_delivery_retries.resolve(item_id, summary.succeeded)
            self.image_delivery_retries.resolve(item_id, summary.uncertain)
            self._log_uncertain_image_delivery(
                item_id,
                summary.uncertain,
                phase="retry",
            )
            failed = set(summary.failed) - set(summary.uncertain)
            attempts_by_target = dict(retries)
            exhausted = [
                target
                for target in failed
                if (
                    attempts_by_target.get(target, 0) + 1
                    >= self.image_retry_max_attempts
                )
            ]
            self.image_delivery_retries.record_failed(
                item_id,
                failed - set(exhausted),
            )
            self.image_delivery_retries.resolve(item_id, exhausted)
            if exhausted:
                await self._notify_content_delivery_failure(
                    record.item,
                    record.uid,
                    [
                        target.target_id
                        for target in exhausted
                        if target.target_type == "group"
                    ],
                    [
                        target.target_id
                        for target in exhausted
                        if target.target_type == "private"
                    ],
                )

    def _record_image_delivery_failures(
        self,
        item: dict[str, Any],
        targets: list[MessageTarget],
    ) -> None:
        if self.image_delivery_retries is None:
            return
        item_id = dynamic_id(item)
        if not item_id:
            return
        self.image_delivery_retries.record_failed(item_id, targets)

    @staticmethod
    def _log_uncertain_image_delivery(
        item_id: str | None,
        targets: tuple[MessageTarget, ...],
        *,
        phase: str,
    ) -> None:
        if not targets:
            return
        logger.warning(
            "%s %s delivery left unconfirmed; skipping retry to avoid duplicate "
            "media: dynamic=%s targets=%s",
            FULL_DYNAMIC_IMAGE_PUSH_ACTION,
            phase,
            item_id,
            [f"{target.target_type}:{target.target_id}" for target in targets],
        )

    def _retry_image_targets(
        self,
        author_mid: int,
        retries: list[tuple[MessageTarget, int]],
    ) -> BiliPushTargets:
        if self.retry_targets_for_uid is None:
            return BiliPushTargets([], [], [], [])
        configured = self.retry_targets_for_uid(author_mid)
        subscription_key = bili_push_subscription_key(author_mid)
        eligible = self._media_targets(
            self._subscribed_full_targets(configured, subscription_key),
            author_mid,
            "image",
        )
        retry_target_set = {target for target, _attempts in retries}
        return BiliPushTargets(
            [
                group_id
                for group_id in eligible.full_group_ids
                if MessageTarget("group", group_id) in retry_target_set
            ],
            [],
            [
                user_id
                for user_id in eligible.full_user_ids
                if MessageTarget("private", user_id) in retry_target_set
            ],
            [],
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
                "%s exhausted adaptive delivery without an admin notice service: "
                "author=%s dynamic=%s groups=%s users=%s",
                FULL_DYNAMIC_PUSH_ACTION,
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
            "累计投递仍未确认，已停止后续重试以避免重复图片。\n"
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
            message_limiter=partial(
                self._transform_target_message,
                author_mid=author_mid,
            ),
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
        *,
        author_mid: int | None = None,
    ) -> Any:
        if self.message_limiter is not None:
            message = self.message_limiter(message, target)
        hints: list[str] = []
        if self.can_query_history is not None and self.can_query_history(target):
            hints.append(DYNAMIC_HISTORY_HINT)
        if (
            self.media_preferences_uid is not None
            and author_mid == self.media_preferences_uid
            and self.subscriptions.mark_daily_hint_sent(
                target.target_type,
                target.target_id,
                SEER_DYNAMIC_TAG_UNSUBSCRIBE_HINT_KEY,
            )
        ):
            hints.append(SEER_DYNAMIC_TAG_UNSUBSCRIBE_HINT)
        if target.target_type == "group" and self.subscriptions.mark_daily_hint_sent(
            "group",
            target.target_id,
            BILI_PUSH_ADMIN_HINT_KEY,
        ):
            hints.append(BILI_PUSH_ADMIN_HINT)
        if not hints:
            return message.rstrip() if isinstance(message, str) else message
        return self.append_hint(message, "\n".join(hints))
