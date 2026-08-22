import asyncio
import struct
from datetime import datetime, timedelta, timezone

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.headless_seer.packets.head import HeadInfo
from ironsbot.integrations.headless_seer.packets.maintenance import (
    decode_maintenance_notice,
)
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_maintenance import HeadlessMaintenanceEvent
from tests.test_headless_notice_runtime import build_service


@pytest.mark.parametrize("body", [b"", b"\x00", b"\x00" * 3, b"\x00" * 5])
def test_rejects_undocumented_payload_shapes(body: bytes) -> None:
    with pytest.raises(ValueError, match="length"):
        decode_maintenance_notice(body)


@pytest.mark.parametrize("value", [0, 1_800_000_000, 2_147_483_648, 4_294_967_295])
def test_unsigned_unix_seconds_follow_flash_client_protocol(value: int) -> None:
    event = decode_maintenance_notice(struct.pack("!I", value))
    assert event.raw_value == value
    assert event.scheduled_at == datetime.fromtimestamp(value, tz=timezone.utc)


def test_notifications_expire_deduplicate_and_allow_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    service = build_service(now=lambda: now)
    sent: list[tuple[str, object]] = []

    async def send(
        _self: AdminNoticeService, message: object, **kwargs: object
    ) -> None:
        sent.append((str(message), kwargs.get("subscription_key")))

    monkeypatch.setattr(AdminNoticeService, "send", send)

    async def run() -> None:
        await service.handle_maintenance_notice(decode_maintenance_notice(b"\x00" * 4))
        await service.handle_maintenance_notice(
            HeadlessMaintenanceEvent(0, now - timedelta(seconds=1))
        )
        await service.handle_maintenance_notice(HeadlessMaintenanceEvent(0, now))
        await service.handle_maintenance_notice(
            HeadlessMaintenanceEvent(0, now.replace(tzinfo=None))
        )
        assert not sent
        # Synthetic service inputs exercise delivery, not the wire time contract.
        event = HeadlessMaintenanceEvent(1, now + timedelta(minutes=10))
        await asyncio.gather(
            *(service.handle_maintenance_notice(event) for _ in range(8))
        )
        await service.handle_maintenance_notice(
            HeadlessMaintenanceEvent(2, now + timedelta(minutes=20))
        )

    asyncio.run(run())
    assert [key for _, key in sent] == ["headless_seer_notice"] * 2
    assert "2026-10-19 08:10:00" in sent[0][0]


def test_protocol_fixture_reaches_admin_sender_through_game_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Generated from the documented uint32 Unix-seconds contract, not captured.
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    service = build_service(now=lambda: now)
    sent: list[tuple[str, object]] = []

    async def send(
        _self: AdminNoticeService, message: object, **kwargs: object
    ) -> None:
        sent.append((str(message), kwargs.get("subscription_key")))

    monkeypatch.setattr(AdminNoticeService, "send", send)

    async def run() -> None:
        async def observe(event: HeadlessMaintenanceEvent) -> None:
            await service.handle_maintenance_notice(event)

        owner = TaskOwner()
        game = SeerGame(
            123456,
            "test-only",
            login_server_url="https://example.invalid",
            operations=HeadlessOperationTracker(),
            spawn=owner.create,
            maintenance_notifier=observe,
        )
        head = HeadInfo("1", COMMAND_ID.SERVER_MAINTENANCE_NOTICE, 123456, 0)
        deadline = int((now + timedelta(minutes=10)).timestamp())
        for value in (0, int(now.timestamp()) - 1, deadline, deadline, deadline + 60):
            game._handle_maintenance_packet(head, struct.pack("!I", value))
        await asyncio.gather(*tuple(owner.tasks))
        game.logout()

    asyncio.run(run())
    assert [key for _, key in sent] == ["headless_seer_notice"] * 2
    assert "2026-10-19 08:10:00" in sent[0][0]


def test_delivery_exception_does_not_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    service = build_service(now=lambda: now)

    async def fail(
        _self: AdminNoticeService, _message: object, **_kwargs: object
    ) -> None:
        raise RuntimeError

    monkeypatch.setattr(AdminNoticeService, "send", fail)
    asyncio.run(
        service.handle_maintenance_notice(
            HeadlessMaintenanceEvent(1, now + timedelta(minutes=1))
        )
    )


def test_game_observer_failure_and_shutdown_do_not_escape() -> None:
    async def run() -> None:
        owner = TaskOwner()
        observed: list[HeadlessMaintenanceEvent] = []

        async def observer(event: HeadlessMaintenanceEvent) -> None:
            observed.append(event)
            raise RuntimeError

        game = SeerGame(
            123456,
            "test-only",
            login_server_url="https://example.invalid",
            operations=HeadlessOperationTracker(),
            spawn=owner.create,
            maintenance_notifier=observer,
        )
        head = HeadInfo("1", COMMAND_ID.SERVER_MAINTENANCE_NOTICE, 123456, 0)
        game._handle_maintenance_packet(head, b"\x00")
        body = struct.pack("!I", 1_800_000_000)
        game._handle_maintenance_packet(head, body)
        await asyncio.sleep(0)
        assert observed == [decode_maintenance_notice(body)]
        game.logout()
        game._handle_maintenance_packet(head, struct.pack("!I", 1_800_000_001))
        await asyncio.sleep(0)
        assert observed == [decode_maintenance_notice(body)]

    asyncio.run(run())
