from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ironsbot.integrations.qq_official.inbound_deduplication import (
    QQOfficialInboundDeduplicator,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_claim_is_persistent_and_account_scoped(tmp_path: Path) -> None:
    path = tmp_path / "claims.sqlite"
    first = QQOfficialInboundDeduplicator(path)

    assert await first.claim(app_id="app-a", event_type="group", message_id="1")
    assert not await first.claim(
        app_id="app-a",
        event_type="group",
        message_id="1",
    )
    assert await first.claim(app_id="app-b", event_type="group", message_id="1")
    assert await first.claim(app_id="app-a", event_type="c2c", message_id="1")

    after_restart = QQOfficialInboundDeduplicator(path)
    assert not await after_restart.claim(
        app_id="app-a",
        event_type="group",
        message_id="1",
    )


@pytest.mark.asyncio
async def test_expired_claim_can_be_processed_again(tmp_path: Path) -> None:
    now = 100.0
    deduplicator = QQOfficialInboundDeduplicator(
        tmp_path / "claims.sqlite",
        retention_seconds=10.0,
        clock=lambda: now,
    )
    assert await deduplicator.claim(
        app_id="app",
        event_type="group",
        message_id="message",
    )

    now = 111.0
    assert await deduplicator.claim(
        app_id="app",
        event_type="group",
        message_id="message",
    )


@pytest.mark.asyncio
async def test_concurrent_delivery_has_one_winner(tmp_path: Path) -> None:
    deduplicator = QQOfficialInboundDeduplicator(tmp_path / "claims.sqlite")

    results = await asyncio.gather(
        *(
            deduplicator.claim(
                app_id="app",
                event_type="group",
                message_id="message",
            )
            for _ in range(8)
        )
    )

    assert results.count(True) == 1
