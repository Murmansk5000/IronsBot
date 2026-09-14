# SPDX-License-Identifier: MIT
"""Platform-neutral delivery for monitored Bilibili dynamics."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import (
    BinaryImagePart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ConversationRef
from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_image_urls,
    dynamic_url,
    item_author_mid,
    item_author_name,
)
from ironsbot.services.bilibili.preferences import (
    bili_media_subscription_key,
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.messaging.image_collage import (
    MIN_COLLAGE_IMAGES,
    ImageCollageError,
)
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryRequest,
    append_outbound_text_once,
)

if TYPE_CHECKING:
    from ironsbot.services.bilibili.content import DynamicContentCompactor
    from ironsbot.services.bilibili.dynamic_history import BiliDynamicHistoryStore
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.image_collage import ImageCollageService
    from ironsbot.services.messaging.proactive_delivery import (
        ProactiveMessageDelivery,
    )
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


FULL_DYNAMIC_PUSH_ACTION = "Bilibili dynamic content push"
LINK_DYNAMIC_PUSH_ACTION = "Bilibili dynamic link push"
BILI_PUSH_ADMIN_HINT = (
    "群主/管理员可发送：B站账号 / B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>"
)
BILI_PUSH_ADMIN_HINT_KEY = "bilibili_admin_hint"
DYNAMIC_HISTORY_HINT = "回复“动态”查询历史动态"
CATEGORY_SUBSCRIPTION_HINT = "发送 TD 可按标签管理动态订阅。"
CATEGORY_SUBSCRIPTION_HINT_KEY = "bilibili_category_subscription_hint"
DYNAMIC_PUSH_INTERVAL_SECONDS = 1.2
FULL_DYNAMIC_CONTENT_FAILURE_SUBSCRIPTION_KEY = "admin_notice"
FULL_DYNAMIC_CONTENT_FAILURE_ACTION = "Bilibili dynamic content delivery failure"

HistoryQueryChecker = Callable[[ConversationRef], bool]
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BilibiliDynamicOutboundSender:
    """Send dynamic text and remote images through the shared outbound port."""

    delivery: ProactiveMessageDelivery
    subscriptions: PushSubscriptionRepository
    content_compactor: DynamicContentCompactor | None = None
    history: BiliDynamicHistoryStore | None = None
    can_query_history: HistoryQueryChecker | None = None
    admin_notices: AdminNoticeService | None = None
    has_category_subscriptions: Callable[[int], bool] | None = None
    image_collage: ImageCollageService | None = None
    combine_images: bool = True

    async def send(
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
        _categories: tuple[str, ...] = (),
    ) -> None:
        subscription_key = bili_push_subscription_key(author_mid)
        link_message = render_dynamic_link_message(item, pub_ts)
        if link_message is None:
            return

        await self._send_link_message(
            link_message,
            targets.link_group_conversations,
            targets.link_private_conversations,
            action_name=LINK_DYNAMIC_PUSH_ACTION,
            subscription_key=subscription_key,
            author_mid=author_mid,
        )

        full_targets = self._subscribed_full_targets(targets, subscription_key)
        if not full_targets.has_targets:
            return
        await self._send_link_message(
            link_message,
            full_targets.full_group_conversations,
            full_targets.full_private_conversations,
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} link",
            subscription_key=subscription_key,
            author_mid=author_mid,
        )

        text_targets = self._subscribed_full_targets(
            full_targets,
            bili_media_subscription_key(author_mid, "text"),
        )
        if text_targets.has_targets:
            compacted = (
                await self.content_compactor.compact(dynamic_content(item))
                if self.content_compactor is not None
                else None
            )
            content_override = compacted.display_text if compacted is not None else None
            if (
                compacted is not None
                and self.history is not None
                and (item_id := str(item.get("id_str", "")).strip())
            ):
                self.history.save_summary(
                    item_id,
                    compacted.text,
                    generated_by_ai=compacted.generated_by_ai,
                )
            content_message = render_dynamic_text_message(item, content_override)
        else:
            content_message = None
        if content_message is not None:
            await self._send_content(
                item,
                author_mid,
                content_message,
                text_targets,
            )

        image_targets = self._subscribed_full_targets(
            full_targets,
            bili_media_subscription_key(author_mid, "image"),
        )
        image_message = (
            await prepare_dynamic_image_message(
                item,
                image_collage=self.image_collage,
                combine_images=self.combine_images,
            )
            if image_targets.has_targets
            else None
        )
        if image_message is not None:
            await self._send_content(
                item,
                author_mid,
                image_message,
                image_targets,
            )

    async def _send_link_message(  # noqa: PLR0913 - separate target collections
        self,
        message: OutboundMessage,
        group_conversations: Iterable[ConversationRef],
        private_conversations: Iterable[ConversationRef],
        *,
        action_name: str,
        subscription_key: str,
        author_mid: int,
    ) -> None:
        await self.delivery.send_many(
            (
                ProactiveDeliveryRequest(
                    conversation,
                    self._target_link_message(
                        message,
                        conversation,
                        author_mid=author_mid,
                    ),
                )
                for conversation in (*group_conversations, *private_conversations)
            ),
            action_name=action_name,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            subscription_key=subscription_key,
            include_promotions=True,
        )

    async def _send_content(
        self,
        item: dict[str, Any],
        author_mid: int,
        content_message: OutboundMessage,
        targets: BiliPushTargets,
    ) -> None:
        conversations = (
            *targets.full_group_conversations,
            *targets.full_private_conversations,
        )
        summary = await self.delivery.send(
            content_message,
            conversations,
            action_name=FULL_DYNAMIC_PUSH_ACTION,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
        )
        if summary.failed:
            await self._notify_content_delivery_failure(
                item,
                author_mid,
                summary.failed,
            )

    async def _notify_content_delivery_failure(
        self,
        item: dict[str, Any],
        author_mid: int,
        conversations: tuple[ConversationRef, ...],
    ) -> None:
        if self.admin_notices is None:
            _LOGGER.error(
                "%s failed after shared delivery policy without an admin notice "
                "service: "
                "author=%s dynamic=%s targets=%s",
                FULL_DYNAMIC_PUSH_ACTION,
                author_mid,
                item.get("id_str", "unknown"),
                conversations,
            )
            return
        target_lines = [
            f"{'群' if conversation.kind == 'group' else '私聊'}：{conversation.id}"
            for conversation in conversations
        ]
        await self.admin_notices.send_private_to_superusers(
            "⚠️ B站动态正文/图片发送失败\n"
            "已按统一推送策略重试，仍未完成。\n"
            f"UID：{author_mid}\n"
            f"动态ID：{item.get('id_str', '未知')}\n"
            f"失败目标：{'；'.join(target_lines)}\n"
            "请检查当前平台的富媒体上传通道。",
            subscription_key=FULL_DYNAMIC_CONTENT_FAILURE_SUBSCRIPTION_KEY,
            action_name=FULL_DYNAMIC_CONTENT_FAILURE_ACTION,
        )

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

    def _target_link_message(
        self,
        message: OutboundMessage,
        conversation: ConversationRef,
        *,
        author_mid: int | None = None,
    ) -> OutboundMessage:
        result = message
        if self.can_query_history is not None and self.can_query_history(conversation):
            result = append_outbound_text_once(result, DYNAMIC_HISTORY_HINT)
        if (
            self.has_category_subscriptions is not None
            and author_mid is not None
            and self.has_category_subscriptions(author_mid)
            and self.subscriptions.mark_daily_hint_sent(
                conversation,
                CATEGORY_SUBSCRIPTION_HINT_KEY,
            )
        ):
            result = append_outbound_text_once(result, CATEGORY_SUBSCRIPTION_HINT)
        if conversation.kind == "group" and self.subscriptions.mark_daily_hint_sent(
            conversation,
            BILI_PUSH_ADMIN_HINT_KEY,
        ):
            result = append_outbound_text_once(result, BILI_PUSH_ADMIN_HINT)
        return result


def render_dynamic_link_message(
    item: dict[str, Any],
    pub_ts: int,
) -> OutboundMessage | None:
    """Render the portable link-only representation of a Bilibili dynamic."""

    try:
        author_name = item_author_name(item)
        author_mid = item_author_mid(item)
        time_str = (
            datetime.fromtimestamp(pub_ts, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        return OutboundMessage(
            (
                TextPart(
                    f"🔔 【{author_name}】发布了一条B站动态\n"
                    f"👤 UID：{author_mid or '未知'}\n"
                    f"⏰ 发布时间：{time_str}\n\n"
                    f"传送门：{dynamic_url(item)}"
                ),
            )
        )
    except (TypeError, ValueError, KeyError):
        _LOGGER.exception("failed to render Bilibili dynamic link")
        return None


def render_dynamic_text_message(
    item: dict[str, Any],
    content_override: str | None = None,
) -> OutboundMessage | None:
    """Render dynamic body text independently from source images."""

    try:
        content = (content_override or dynamic_content(item)).strip()
    except (TypeError, ValueError, KeyError):
        _LOGGER.exception("failed to render Bilibili dynamic text")
        return None
    return OutboundMessage.from_text(content) if content else None


async def render_dynamic_content_message(
    item: dict[str, Any],
    content_override: str | None = None,
    *,
    image_collage: ImageCollageService | None = None,
    combine_images: bool = True,
) -> OutboundMessage | None:
    """Render the complete portable body used by interactive history queries."""

    text = render_dynamic_text_message(item, content_override)
    images = await prepare_dynamic_image_message(
        item,
        image_collage=image_collage,
        combine_images=combine_images,
    )
    parts = (
        *(text.parts if text is not None else ()),
        *(images.parts if images is not None else ()),
    )
    return OutboundMessage(parts) if parts else None


async def prepare_dynamic_image_message(
    item: dict[str, Any],
    *,
    image_collage: ImageCollageService | None,
    combine_images: bool,
) -> OutboundMessage | None:
    """Share adaptive images and lossless failure fallback across query and push."""
    fallback = render_dynamic_image_message(item)
    if fallback is None or image_collage is None or not combine_images:
        return fallback
    urls = tuple(
        part.url for part in fallback.parts if isinstance(part, RemoteImagePart)
    )
    if len(urls) < MIN_COLLAGE_IMAGES:
        return fallback
    try:
        content = await image_collage.compose_urls(urls)
        return OutboundMessage((BinaryImagePart(content, "image/png"),))
    except ImageCollageError as error:
        _LOGGER.warning(
            "Bilibili collage fallback: dynamic=%s reason=%s", item.get("id_str"), error
        )
    except Exception:
        _LOGGER.exception("Bilibili collage failed: dynamic=%s", item.get("id_str"))
    return fallback


def render_dynamic_image_message(item: dict[str, Any]) -> OutboundMessage | None:
    """Render dynamic source images independently from text delivery."""

    try:
        parts = tuple(
            RemoteImagePart(url)
            for raw_url in dynamic_image_urls(item)
            if (url := raw_url.strip().rstrip("]"))
        )
    except (TypeError, ValueError, KeyError):
        _LOGGER.exception("failed to render Bilibili dynamic images")
        return None
    return OutboundMessage(tuple(parts)) if parts else None
