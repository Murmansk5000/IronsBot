# SPDX-License-Identifier: MIT
"""Correlated push summaries without message bodies, URLs or private addresses."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, RemoteImagePart

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.bilibili.target_models import BiliPushTargets

logger = logging.getLogger(__name__)


def push_started(
    dynamic_id: str, uid: int, targets: BiliPushTargets, *, resume: bool
) -> float:
    logger.info(
        "Bilibili push started: dynamic=%s uid=%d resume=%s full_groups=%d "
        "full_privates=%d link_groups=%d link_privates=%d",
        dynamic_id,
        uid,
        resume,
        len(targets.full_group_conversations),
        len(targets.full_private_conversations),
        len(targets.link_group_conversations),
        len(targets.link_private_conversations),
    )
    return time.monotonic()


def media_started(dynamic_id: str) -> float:
    logger.info("Bilibili media preparation started: dynamic=%s", dynamic_id)
    return time.monotonic()


def preparation_failed(dynamic_id: str, error: Exception) -> None:
    # Exception text can contain authenticated source URLs; log types only.
    logger.warning(
        "Bilibili media preparation failed: dynamic=%s exception=%s cause=%s",
        dynamic_id,
        type(error).__name__,
        type(error.__cause__ or error.__context__).__name__,
    )


def media_ready(
    dynamic_id: str, message: OutboundMessage | None, started: float, *, cached: bool
) -> None:
    parts = message.parts if message else ()
    logger.info(
        "Bilibili media ready: dynamic=%s frozen_cache=%s units=%d elapsed_ms=%d",
        dynamic_id,
        cached,
        len(parts),
        int((time.monotonic() - started) * 1000),
    )
    for index, part in enumerate(parts, 1):
        if isinstance(part, BinaryImagePart):
            logger.info(
                "Bilibili prepared unit: dynamic=%s unit=image:%d bytes=%d "
                "content_type=%s sha256=%s",
                dynamic_id,
                index,
                len(part.content),
                part.content_type,
                hashlib.sha256(part.content).hexdigest(),
            )
        elif isinstance(part, RemoteImagePart):
            logger.info(
                "Bilibili prepared unit: dynamic=%s unit=image:%d source=remote "
                "bytes=unknown",
                dynamic_id,
                index,
            )


def push_finished(
    dynamic_id: str,
    started: float,
    states: dict[str, int],
    failures: int,
    *,
    deferred: bool,
) -> None:
    logger.info(
        "Bilibili push summary: dynamic=%s elapsed_ms=%d deferred=%s "
        "states=%s failed_units=%d",
        dynamic_id,
        int((time.monotonic() - started) * 1000),
        deferred,
        dict(sorted(states.items())),
        failures,
    )
