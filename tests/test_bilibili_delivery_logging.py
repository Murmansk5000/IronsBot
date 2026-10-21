from __future__ import annotations

import asyncio
import hashlib
import logging

import httpx
import pytest

from ironsbot.core.delivery_attempt import delivery_round, delivery_unit
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, RemoteImagePart
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.bilibili.delivery_logging import (
    media_ready,
    media_started,
    preparation_failed,
)
from ironsbot.services.bilibili.delivery_rounds import DynamicRetryPlan
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryPolicy


@pytest.mark.parametrize("cached", [True, False])
def test_frozen_unit_logs_safe_content_identity(
    caplog: pytest.LogCaptureFixture, *, cached: bool
) -> None:
    content = b"private image bytes"
    message = OutboundMessage(
        (
            BinaryImagePart(content, "image/png", filename="private-name.png"),
            RemoteImagePart("https://example.test/private?signature=secret"),
        )
    )
    with caplog.at_level(logging.INFO):
        started = media_started("test-dynamic")
        media_ready("test-dynamic", message, started, cached=cached)
    assert f"frozen_cache={cached} units=2" in caplog.text
    assert f"bytes={len(content)}" in caplog.text
    assert hashlib.sha256(content).hexdigest() in caplog.text
    assert "unit=image:2 source=remote bytes=unknown" in caplog.text
    for secret in ("private image", "private-name", "signature", "https://"):
        assert secret not in caplog.text


def test_preparation_failure_does_not_log_authenticated_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = RuntimeError("private password")
    error.__cause__ = httpx.ReadTimeout("https://example.test/?signature=secret")
    preparation_failed("test-dynamic", error)
    assert "exception=RuntimeError cause=ReadTimeout" in caplog.text
    assert "password" not in caplog.text
    assert "signature" not in caplog.text


@pytest.mark.asyncio
async def test_round_context_and_batch_are_isolated_and_restored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    targets = [
        ConversationRef(Platform.ONEBOT, "group", f"private-target-{number}")
        for number in range(3)
    ]
    seen = []

    async def send(target: ConversationRef) -> None:
        await asyncio.sleep(0)
        seen.append((target, delivery_round.get(), delivery_unit.get()))

    parent_round = 7
    marker = delivery_round.set(parent_round)
    try:
        with caplog.at_level(logging.INFO):
            await DynamicRetryPlan(
                "test-dynamic", ProactiveDeliveryPolicy(max_parallel_targets=2)
            ).run(targets, send, {}, resume=False)
        assert delivery_round.get() == parent_round
    finally:
        delivery_round.reset(marker)
    assert [target for target, _, _ in seen] == targets
    assert all(number == 1 for _, number, _ in seen)
    assert "batch_size=2 batches=2" in caplog.text
    assert "round=1 batch=2" in caplog.text
    assert "private-target" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("secret"), asyncio.CancelledError()])
async def test_aborted_target_restores_round_context(
    error: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    async def send(_target: ConversationRef) -> None:
        raise error

    target = ConversationRef(Platform.ONEBOT, "group", "private-target")
    with caplog.at_level(logging.INFO), pytest.raises(type(error)):
        await DynamicRetryPlan("test-dynamic", ProactiveDeliveryPolicy()).run(
            [target], send, {}, resume=False
        )
    assert delivery_round.get() == 0
    assert "Bilibili target finished:" in caplog.text
    assert "secret" not in caplog.text
