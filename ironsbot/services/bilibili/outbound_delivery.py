# SPDX-License-Identifier: MIT
"""Platform-neutral delivery for monitored Bilibili dynamics."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    OutboundMessage,
    RemoteImagePart,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, reference_digest
from ironsbot.core.time import TZ_CN
from ironsbot.services.bilibili.delivery_ledger import StageMessenger
from ironsbot.services.bilibili.parser import (
    dynamic_body_hydration_reason,
    dynamic_content,
    dynamic_delivery_content,
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
from ironsbot.services.messaging.image_collage import ImageCollageError
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryRequest,
    append_outbound_text_once,
)

if TYPE_CHECKING:
    from ironsbot.services.bilibili.content import DynamicContentCompactor
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger
    from ironsbot.services.bilibili.dynamic_history import BiliDynamicHistoryStore
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.image_collage import ImageCollageService
    from ironsbot.services.messaging.proactive_delivery import (
        ProactiveDeliverySummary,
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
FailureKey = tuple[ConversationRef, str]


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
    category_labels: Callable[[int, tuple[str, ...]], tuple[str, ...]] | None = None
    account_name: Callable[[int], str | None] | None = None
    image_collage: ImageCollageService | None = None
    combine_images: bool = True
    ledger: DynamicDeliveryLedger | None = None

    async def send(  # noqa: PLR0913 - ordered independent delivery stages
        self,
        item: dict[str, Any],
        pub_ts: int,
        author_mid: int,
        targets: BiliPushTargets,
        categories: tuple[str, ...] = (),
        *,
        resume: bool = False,
    ) -> None:
        if (
            self.ledger is not None
            and not resume
            and not self.ledger.prepare(item, pub_ts, author_mid, targets, categories)
        ):
            return
        dynamic_id = str(item.get("id_str", ""))
        subscription_key = bili_push_subscription_key(author_mid)
        link_message = render_dynamic_link_message(
            item,
            pub_ts,
            fallback_name=self.account_name(author_mid) if self.account_name else None,
        )
        if link_message is None:
            return
        if categories:
            labels = (
                self.category_labels(author_mid, categories)
                if self.category_labels is not None
                else categories
            )
            link_message = OutboundMessage(
                (TextPart("🏷️ 标签：" + " / ".join(labels) + "\n"), *link_message.parts)
            )

        failures: dict[FailureKey, SendResult] = {}
        await self._send_link_message(
            link_message,
            targets.link_group_conversations,
            targets.link_private_conversations,
            action_name=LINK_DYNAMIC_PUSH_ACTION,
            subscription_key=subscription_key,
            author_mid=author_mid,
            dynamic_id=dynamic_id,
            failures=failures,
        )

        full_targets = self._subscribed_full_targets(targets, subscription_key)
        if not full_targets.has_targets:
            await self._finish_delivery(item, author_mid, failures)
            return
        await self._send_link_message(
            link_message,
            full_targets.full_group_conversations,
            full_targets.full_private_conversations,
            action_name=f"{FULL_DYNAMIC_PUSH_ACTION} link",
            subscription_key=subscription_key,
            author_mid=author_mid,
            dynamic_id=dynamic_id,
            failures=failures,
        )

        text_targets = (
            self._subscribed_full_targets(
                full_targets, bili_media_subscription_key(author_mid, "text")
            )
            if self.has_category_subscriptions is not None
            and self.has_category_subscriptions(author_mid)
            else full_targets
        )
        text_targets = self._pending_targets(text_targets, dynamic_id, "text")
        if text_targets.has_targets:
            compacted = (
                await self.content_compactor.compact(dynamic_content(item))
                if self.content_compactor is not None
                and dynamic_body_hydration_reason(item) is None
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
                content_message,
                text_targets,
                failures,
                dynamic_id=dynamic_id,
                stage="text",
            )

        image_targets = (
            self._subscribed_full_targets(
                full_targets, bili_media_subscription_key(author_mid, "image")
            )
            if self.has_category_subscriptions is not None
            and self.has_category_subscriptions(author_mid)
            else full_targets
        )
        image_targets = self._pending_targets(image_targets, dynamic_id, "image")
        image_message = (
            await prepare_dynamic_image_message(
                item, self.image_collage, combine_images=self.combine_images
            )
            if image_targets.has_targets
            else None
        )
        if image_message is not None and image_targets.has_targets:
            await self._send_content(
                image_message,
                image_targets,
                failures,
                dynamic_id=dynamic_id,
                stage="image",
            )
        await self._finish_delivery(item, author_mid, failures)

    async def _finish_delivery(
        self,
        item: dict[str, Any],
        author_mid: int,
        failures: dict[FailureKey, SendResult],
    ) -> None:
        dynamic_id = str(item.get("id_str", ""))
        if self.ledger is not None:
            self.ledger.skip_remaining(dynamic_id)
        if failures and (
            self.ledger is None or self.ledger.claim_notification(dynamic_id)
        ):
            await self._notify_content_delivery_failure(
                item,
                author_mid,
                failures,
            )

    def _stage_delivery(self, dynamic_id: str, stage: str) -> ProactiveMessageDelivery:
        if self.ledger is None:
            return self.delivery
        return replace(
            self.delivery,
            messenger=StageMessenger(
                self.delivery.messenger, self.ledger, dynamic_id, stage
            ),
        )

    def _pending_targets(
        self,
        targets: BiliPushTargets,
        dynamic_id: str,
        stage: str,
    ) -> BiliPushTargets:
        if self.ledger is None:
            return targets
        return replace(
            targets,
            full_group_conversations=[
                target
                for target in targets.full_group_conversations
                if self.ledger.unattempted(dynamic_id, target, stage)
            ],
            full_private_conversations=[
                target
                for target in targets.full_private_conversations
                if self.ledger.unattempted(dynamic_id, target, stage)
            ],
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
        dynamic_id: str,
        failures: dict[FailureKey, SendResult],
    ) -> None:
        summary = await self._stage_delivery(dynamic_id, "link").send_many(
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
                if self.ledger is None
                or self.ledger.unattempted(dynamic_id, conversation, "link")
            ),
            action_name=action_name,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            subscription_key=subscription_key,
            include_promotions=True,
            max_attempts=1,
        )
        self._capture_failures(summary, failures, stage="link")

    async def _send_content(
        self,
        content_message: OutboundMessage,
        targets: BiliPushTargets,
        failures: dict[FailureKey, SendResult],
        *,
        dynamic_id: str,
        stage: str,
    ) -> None:
        conversations = (
            *targets.full_group_conversations,
            *targets.full_private_conversations,
        )
        summary = await self._stage_delivery(dynamic_id, stage).send(
            content_message,
            conversations,
            action_name=FULL_DYNAMIC_PUSH_ACTION,
            interval_seconds=DYNAMIC_PUSH_INTERVAL_SECONDS,
            max_attempts=1,
        )
        self._capture_failures(summary, failures, stage=stage)

    @staticmethod
    def _capture_failures(
        summary: ProactiveDeliverySummary,
        failures: dict[FailureKey, SendResult],
        *,
        stage: str,
    ) -> None:
        failed = set(summary.failed)
        recorded: set[ConversationRef] = set()
        for conversation, result in summary.results:
            recorded.add(conversation)
            if (
                conversation in failed
                and not result.delivered
                and result.attempted
                and result.failure_kind is not DeliveryFailureKind.TRANSPORT_UNAVAILABLE
            ):
                failures[(conversation, stage)] = result
        for conversation in failed - recorded:
            failures[(conversation, stage)] = SendResult(
                delivered=False,
                error_code="delivery_failed",
                failure_kind=DeliveryFailureKind.PERMANENT,
            )

    async def _notify_content_delivery_failure(
        self,
        item: dict[str, Any],
        author_mid: int,
        failures: dict[FailureKey, SendResult],
    ) -> None:
        if self.admin_notices is None:
            _LOGGER.error(
                "%s failed after shared delivery policy without an admin notice "
                "service: "
                "author=%s dynamic=%s targets=%s",
                FULL_DYNAMIC_PUSH_ACTION,
                author_mid,
                item.get("id_str", "unknown"),
                tuple(
                    (
                        conversation.platform.value,
                        conversation.kind,
                        reference_digest(conversation.id),
                        stage,
                    )
                    for conversation, stage in failures
                ),
            )
            return
        grouped: dict[ConversationRef, list[tuple[str, SendResult]]] = {}
        for (conversation, stage), result in failures.items():
            grouped.setdefault(conversation, []).append((stage, result))
        target_lines: list[str] = []
        stage_labels = {"link": "链接", "text": "正文", "image": "图片"}
        for conversation, stage_results in grouped.items():
            stages = "、".join(
                stage_labels.get(stage, stage) for stage, _result in stage_results
            )
            identities = tuple(
                dict.fromkeys(
                    result.execution_identity
                    for _stage, result in stage_results
                    if result.execution_identity is not None
                )
            )
            identity_text = "、".join(identity.describe() for identity in identities)
            target_lines.append(
                f"失败目标：{'群' if conversation.kind == 'group' else '私聊'} "
                f"{conversation.id}\n失败阶段：{stages}\n执行机器人："
                f"{identity_text or '未确定'}"
            )
        name = item_author_name(item)
        if name in {f"UID {author_mid}", "该账号"}:
            name = (
                self.account_name(author_mid) if self.account_name else None
            ) or name
        await self.admin_notices.send_private_to_superusers(
            "⚠️ B站动态部分阶段发送失败\n"
            "列出的阶段未完成，不自动补发；其他成功阶段不受影响。\n"
            f"B站账号：{name}（UID：{author_mid}）\n"
            f"动态ID：{item.get('id_str', '未知')}\n" + "\n".join(target_lines) + "\n"
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
    *,
    fallback_name: str | None = None,
) -> OutboundMessage | None:
    """Render the portable link-only representation of a Bilibili dynamic."""

    try:
        author_name = item_author_name(item)
        author_mid = item_author_mid(item)
        if fallback_name and author_name in {f"UID {author_mid}", "该账号"}:
            author_name = fallback_name
        time_str = datetime.fromtimestamp(pub_ts, tz=TZ_CN).strftime(
            "%Y-%m-%d %H:%M:%S"
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
        content = (content_override or dynamic_delivery_content(item)).strip()
    except (TypeError, ValueError, KeyError):
        _LOGGER.exception("failed to render Bilibili dynamic text")
        return None
    return OutboundMessage.from_text(content) if content else None


def render_dynamic_content_message(
    item: dict[str, Any],
    content_override: str | None = None,
) -> OutboundMessage | None:
    """Render the complete portable body used by interactive history queries."""

    text = render_dynamic_text_message(item, content_override)
    images = render_dynamic_image_message(item)
    parts = (
        *(text.parts if text is not None else ()),
        *(images.parts if images is not None else ()),
    )
    return OutboundMessage(parts) if parts else None


async def prepare_dynamic_image_message(
    item: dict[str, Any],
    collage: ImageCollageService | None,
    *,
    combine_images: bool = True,
) -> OutboundMessage | None:
    original = render_dynamic_image_message(item)
    if original is None or collage is None or not combine_images:
        return original
    urls = tuple(
        part.url for part in original.parts if isinstance(part, RemoteImagePart)
    )
    if len(urls) <= 1:
        return original
    try:
        prepared = await collage.prepare_urls(urls)
    except ImageCollageError:
        _LOGGER.warning("Bilibili collage unavailable; using original images")
        return original
    parts = tuple(
        RemoteImagePart(image.url)
        if image.url is not None
        else BinaryImagePart(image.content or b"", image.content_type, image.filename)
        for image in prepared
    )
    return OutboundMessage(parts) if parts else None


async def prepare_dynamic_content_messages(
    item: dict[str, Any],
    content_override: str | None,
    collage: ImageCollageService | None,
    *,
    combine_images: bool = True,
) -> tuple[OutboundMessage, ...]:
    text = render_dynamic_text_message(item, content_override)
    images = await prepare_dynamic_image_message(
        item,
        collage,
        combine_images=combine_images,
    )
    return tuple(part for part in (text, images) if part is not None)


async def iter_dynamic_image_messages(
    item: dict[str, Any],
    collage: ImageCollageService | None,
    *,
    combine_images: bool = True,
) -> AsyncIterator[OutboundMessage]:
    """Yield each prepared media group without waiting for slower groups."""

    original = render_dynamic_image_message(item)
    if original is None:
        return
    urls = tuple(
        part.url for part in original.parts if isinstance(part, RemoteImagePart)
    )
    if collage is None or not combine_images or len(urls) <= 1:
        for part in original.parts:
            yield OutboundMessage((part,))
        return
    try:
        async for image in collage.iter_prepared_urls(urls):
            part = (
                RemoteImagePart(image.url)
                if image.url is not None
                else BinaryImagePart(
                    image.content or b"", image.content_type, image.filename
                )
            )
            yield OutboundMessage((part,))
    except ImageCollageError:
        _LOGGER.warning("Bilibili collage unavailable; using original images")
        for part in original.parts:
            yield OutboundMessage((part,))


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
