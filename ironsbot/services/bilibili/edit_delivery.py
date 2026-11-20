# SPDX-License-Identifier: MIT
"""Revision presentation shares preparation limits and existing stage policy."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import OutboundMessage, TextPart

from .media_preparation import MediaPreparationError
from .revisions import delivery_key, revision_meta, visible_signature

if TYPE_CHECKING:
    from .outbound_delivery import BilibiliDynamicOutboundSender
    from .stage_subscriptions import DynamicStagePolicy
    from .target_models import BiliPushTargets

_LOGGER = logging.getLogger(__name__)


async def prepare_edit_text(
    sender: BilibiliDynamicOutboundSender, item: dict[str, Any]
) -> OutboundMessage | None:
    if sender.edit_renderer is not None:
        return await sender.edit_renderer.text(item)
    return OutboundMessage.from_text(
        "正文已修改，对照渲染不可用，请查看动态链接。", request_succeeded=False
    )


async def prepare_edit_media(
    sender: BilibiliDynamicOutboundSender, item: dict[str, Any]
) -> OutboundMessage | None:
    ledger, key = sender.ledger, delivery_key(item)
    if ledger is not None:
        found, fallback = ledger.load_text(key + ":image_fallback")
        if found:
            return fallback
        found, message = ledger.load_media(key)
        if found:
            return message
        attempt, remaining = ledger.begin_media_preparation(
            key, visible_signature(item)
        )
        if not attempt:
            message = "edit comparison preparation budget exhausted"
            raise MediaPreparationError(message)
    else:
        remaining = 60.0
    try:
        message = (
            await asyncio.wait_for(sender.edit_renderer.media(item), timeout=remaining)
            if sender.edit_renderer
            else None
        )
    except Exception:
        if ledger is not None:
            ledger.finish_media_preparation(
                key, "retry", {"reasons": ["comparison_failed"]}
            )
        raise
    if ledger is not None:
        ledger.finish_media_preparation(key, "complete", {})
        if message is not None and any(isinstance(p, TextPart) for p in message.parts):
            return ledger.freeze_text(key + ":image_fallback", message)
        return ledger.freeze_media(key, message)
    return message


async def suppress_invisible_edit(
    sender: BilibiliDynamicOutboundSender,
    item: dict[str, Any],
    targets: BiliPushTargets,
    policy: DynamicStagePolicy,
) -> bool:
    meta = revision_meta(item)
    if (
        not meta.get("images_changed")
        or meta.get("text_changed")
        or not sender.edit_renderer
    ):
        return False
    full = {*targets.full_group_conversations, *targets.full_private_conversations}
    conversations = full | {
        *targets.link_group_conversations,
        *targets.link_private_conversations,
    }
    if not any(
        policy.allowed(target, stage)
        for target in conversations
        for stage in (("link", "image") if target in full else ("link",))
    ):
        return False
    try:
        message = await prepare_edit_media(sender, item)
    except Exception as error:  # noqa: BLE001 - normal stage owns final failure
        _LOGGER.warning(
            "Edit preflight deferred to bounded stages: %s", type(error).__name__
        )
        return False
    if message is not None:
        return False
    if sender.ledger is not None:
        for target in conversations:
            for stage in ("link", "text", "image"):
                sender.ledger.skip_stage(delivery_key(item), target, stage)
    return True
