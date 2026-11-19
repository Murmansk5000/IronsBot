from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    OutboundMessage,
    RemoteImagePart,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.push_routing import PushRouteDecision
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.conversation_queue import wake_ready
from ironsbot.services.bilibili.delivery_lifecycle import own_delivery
from ironsbot.services.bilibili.delivery_recovery import BiliDeliveryRecovery
from ironsbot.services.bilibili.monitor import _push_new_dynamics
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
from tests.helpers.bilibili import build_test_bilibili_service
from tests.test_bilibili_ordered_lifecycle import stage
from tests.test_bilibili_outbound_delivery import _item
from tests.test_proactive_delivery import FakeMessenger, _delivery, _text

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ConversationKind

_NAMES = ("batch-a", "batch-b", "batch-c")
_STAGES = ("link", "text", "image")
_FOUR = 4


def item(name: str) -> dict[str, Any]:
    value = _item(text=name)
    value["id_str"] = name
    value["modules"]["module_dynamic"]["major"]["opus"]["pics"] = [
        {"url": f"https://example.com/{name}.png"}
    ]
    return value


def targets(*values: ConversationRef) -> BiliPushTargets:
    return BiliPushTargets(
        [value for value in values if value.kind == "group"],
        [],
        [value for value in values if value.kind == "private"],
        [],
    )


@dataclass
class QueueMessenger(FakeMessenger):
    seen: list[tuple[str, str, str]] = field(default_factory=list)
    gate: tuple[str, str, str] | None = None
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    failures: dict[tuple[str, str, str], list[DeliveryFailureKind]] = field(
        default_factory=dict
    )

    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        return replace(
            super().capabilities_for(conversation),
            can_send_proactively=True,
            supports_images=True,
        )

    async def send(
        self, conversation: ConversationRef, message: OutboundMessage
    ) -> SendResult:
        content = _text(message) + " ".join(
            part.url for part in message.parts if isinstance(part, RemoteImagePart)
        )
        name = next(value for value in _NAMES if value in content)
        key = (conversation.id, name, stage(message))
        self.seen.append(key)
        self.calls.append((conversation, message))
        if key == self.gate:
            self.entered.set()
            await self.release.wait()
        if self.failures.get(key):
            return SendResult(
                delivered=False,
                error_code="synthetic_rejection",
                failure_kind=self.failures[key].pop(0),
            )
        return SendResult(delivered=True, message_id="synthetic-receipt")


def sender_at(
    path: Path, messenger: QueueMessenger, owner: TaskOwner
) -> BilibiliDynamicOutboundSender:
    delivery, _, subscriptions = _delivery(messenger=messenger)
    return BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=SqliteDynamicDeliveryLedger(path),
        spawn=owner.create,
    )


async def drain(owner: TaskOwner) -> None:
    async def finish() -> None:
        while owner.tasks:
            await asyncio.gather(*tuple(owner.tasks))
            await asyncio.sleep(0)

    await asyncio.wait_for(finish(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("kind", ["group", "private"])
async def test_conversation_fifo_across_accounts_and_later_discovery(
    tmp_path: Path, platform: Platform, kind: ConversationKind
) -> None:
    target = ConversationRef(platform, kind, "synthetic", account_id="bot")
    messenger = QueueMessenger(gate=(target.id, "batch-a", "image"))
    owner = TaskOwner()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    now = int(time.time())
    first = asyncio.ensure_future(
        sender.send(item("batch-a"), now, 700001, targets(target))
    )
    await asyncio.wait_for(messenger.entered.wait(), 5)
    for offset, name in enumerate(_NAMES[1:], 1):
        await sender.send(item(name), now - offset, 700001 + offset, targets(target))
    assert [name for _, name, _ in messenger.seen] == ["batch-a"] * len(_STAGES)
    assert sender.ledger is not None
    with SqliteDatabase(sender.ledger.path).connect() as db:
        assert db.execute(
            "SELECT SUM(attempts),SUM(deadline_at) FROM stages "
            "WHERE dynamic_id!='batch-a'"
        ).fetchone() == (0, 0)
        assert db.execute(
            "SELECT COUNT(*) FROM media_manifests WHERE dynamic_id!='batch-a'"
        ).fetchone() == (0,)
    messenger.release.set()
    await first
    await drain(owner)
    assert [(name, unit) for _, name, unit in messenger.seen] == [
        (name, unit) for name in _NAMES for unit in _STAGES
    ]


@pytest.mark.asyncio
async def test_completed_group_does_not_wait_for_other_group(tmp_path: Path) -> None:
    fast = ConversationRef(Platform.ONEBOT, "group", "fast")
    slow = ConversationRef(Platform.ONEBOT, "group", "slow")
    messenger = QueueMessenger(gate=(slow.id, "batch-a", "image"))
    owner = TaskOwner()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    now = int(time.time())
    first = asyncio.ensure_future(
        sender.send(item("batch-a"), now, 700001, targets(fast, slow))
    )
    await asyncio.wait_for(messenger.entered.wait(), 5)
    await sender.send(item("batch-b"), now, 700002, targets(fast, slow))
    assert (fast.id, "batch-b", "image") in messenger.seen
    assert not any(
        target == slow.id and name == "batch-b" for target, name, _ in messenger.seen
    )
    messenger.release.set()
    await first
    await drain(owner)
    for target in (fast, slow):
        assert [
            (name, unit) for ident, name, unit in messenger.seen if ident == target.id
        ] == [(name, unit) for name in _NAMES[:2] for unit in _STAGES]


@pytest.mark.asyncio
async def test_retry_exhaustion_stays_inside_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    messenger = QueueMessenger(
        failures={
            (target.id, "batch-a", "link"): [DeliveryFailureKind.RETRYABLE] * _FOUR
        }
    )
    owner = TaskOwner()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    now = int(time.time())
    clock = [time.time()]
    sleep = asyncio.sleep

    async def advance(delay: float) -> None:
        clock[0] += delay
        await sleep(0)

    from types import SimpleNamespace

    monkeypatch.setattr(
        "ironsbot.integrations.storage.bilibili_delivery_ledger.time",
        SimpleNamespace(time=lambda: clock[0]),
    )
    monkeypatch.setattr(
        "ironsbot.services.bilibili.delivery_rounds.asyncio.sleep", advance
    )
    sender.enqueue(item("batch-a"), now, 700001, targets(target))
    sender.enqueue(item("batch-b"), now, 700002, targets(target))
    await sender.send(item("batch-b"), now, 700002, targets(target))
    await drain(owner)
    assert [(name, unit) for _, name, unit in messenger.seen] == [
        ("batch-a", "link")
    ] * _FOUR + [("batch-a", "text"), ("batch-a", "image")] + [
        ("batch-b", unit) for unit in _STAGES
    ]


@pytest.mark.asyncio
async def test_uncertain_turn_blocks_only_its_conversation_until_late_receipt(
    tmp_path: Path,
) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "uncertain")
    other = ConversationRef(Platform.ONEBOT, "private", "other")
    messenger = QueueMessenger(gate=(target.id, "batch-a", "link"))
    owner = TaskOwner()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    now = int(time.time())
    first = asyncio.ensure_future(
        sender.send(item("batch-a"), now, 700001, targets(target))
    )
    await asyncio.wait_for(messenger.entered.wait(), 5)
    assert sender.ledger is not None
    # Inject expiration only after the transport has definitely been entered.
    sender.ledger.expire_stage("batch-a", target, "link")
    sender.ledger.block_following("batch-a", target, "link")
    await sender.send(item("batch-b"), now, 700002, targets(target, other))
    assert not any(
        ident == target.id and name == "batch-b" for ident, name, _ in messenger.seen
    )
    assert (other.id, "batch-b", "image") in messenger.seen
    messenger.release.set()
    await first
    await drain(owner)
    assert [
        (name, unit) for ident, name, unit in messenger.seen if ident == target.id
    ] == [("batch-a", "link")] + [("batch-b", unit) for unit in _STAGES]


@pytest.mark.asyncio
async def test_restart_preserves_fifo_and_expiry_does_not_renew(tmp_path: Path) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    owner = TaskOwner()
    messenger = QueueMessenger()
    path = tmp_path / "queue.sqlite"
    first = sender_at(path, messenger, owner)
    now = int(time.time())
    first.enqueue(item("batch-a"), now, 700001, targets(target))
    first.enqueue(item("batch-b"), now, 700002, targets(target))
    with SqliteDatabase(path).connect() as db:
        sequence = db.execute(
            "SELECT sequence,dynamic_id FROM conversation_queue ORDER BY sequence"
        ).fetchall()
    restarted = sender_at(path, messenger, owner)
    assert restarted.ledger is not None
    restarted.ledger.recover()
    await restarted.send(item("batch-b"), now, 700002, targets(target), resume=True)
    await drain(owner)
    assert [(name, unit) for _, name, unit in messenger.seen] == [
        (name, unit) for name in _NAMES[:2] for unit in _STAGES
    ]
    with SqliteDatabase(path).connect() as db:
        assert (
            db.execute(
                "SELECT sequence,dynamic_id FROM conversation_queue ORDER BY sequence"
            ).fetchall()
            == sequence
        )


@pytest.mark.asyncio
async def test_route_change_does_not_move_frozen_target_to_another_bot(
    tmp_path: Path,
) -> None:
    target = ConversationRef(
        Platform.QQ_OFFICIAL, "group", "original", account_id="bot-a"
    )
    changed = ConversationRef(
        Platform.QQ_OFFICIAL, "group", "different", account_id="bot-b"
    )
    owner = TaskOwner()
    messenger = QueueMessenger()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    active = [target]
    routes = PrivateConversationRoutes(
        group_route=lambda _source: PushRouteDecision("ready", active[0])
    )
    sender = replace(sender, delivery=replace(sender.delivery, private_routes=routes))
    now = int(time.time())
    sender.enqueue(item("batch-a"), now, 700001, targets(target))
    active[0] = changed
    wake_ready(sender)
    await drain(owner)
    assert messenger.seen == []
    assert sender.ledger is not None
    assert sender.ledger.stage_state("batch-a", target, "link") == "skipped"


@pytest.mark.asyncio
async def test_cancelled_turn_is_recovered_without_releasing_to_successor(
    tmp_path: Path,
) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "queue.sqlite")
    now = int(time.time())
    for name in _NAMES[:2]:
        ledger.prepare(item(name), now, 700001, targets(target), ())
    async with own_delivery(ledger, "batch-a"):
        assert ledger.queue_claim("batch-a", (target,)) == {target}
        assert ledger.claim("batch-a", target, "link")
    restarted = SqliteDynamicDeliveryLedger(ledger.path)
    restarted.recover()
    assert restarted.queue_ready() == []
    assert restarted.attempts("batch-a", target, "link") == 1
    assert restarted.stage_state("batch-a", target, "link") == "uncertain"
    assert restarted.stage_state("batch-b", target, "link") == "pending"


def test_startup_backfill_does_not_reopen_completed_receipts(tmp_path: Path) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    path = tmp_path / "queue.sqlite"
    ledger = SqliteDynamicDeliveryLedger(path)
    ledger.prepare(item("batch-a"), int(time.time()), 700001, targets(target), ())
    with SqliteDatabase(path).connect() as db:
        db.execute("UPDATE stages SET state='success'")
        db.execute("DROP TABLE conversation_queue")
    migrated = SqliteDynamicDeliveryLedger(path)
    assert migrated.queue_ready() == []
    assert migrated.stage_state("batch-a", target, "link") == "success"
    with SqliteDatabase(path).connect() as db:
        before = db.execute("SELECT sequence,state FROM conversation_queue").fetchall()
    restarted = SqliteDynamicDeliveryLedger(path)
    assert restarted.queue_ready() == []
    with SqliteDatabase(path).connect() as db:
        assert (
            db.execute("SELECT sequence,state FROM conversation_queue").fetchall()
            == before
        )


@dataclass
class AccountGate:
    ready: set[ConversationRef]

    def account_ready(self, target: ConversationRef) -> bool:
        return target in self.ready

    def account_failed(self, target: ConversationRef) -> None:
        self.ready.discard(target)


@pytest.mark.asyncio
async def test_offline_queue_recovery_preserves_order_without_budget(
    tmp_path: Path,
) -> None:
    offline = ConversationRef(Platform.ONEBOT, "group", "offline")
    online = ConversationRef(Platform.ONEBOT, "group", "online")
    gate = AccountGate({online})
    owner = TaskOwner()
    messenger = QueueMessenger()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    sender = replace(
        sender, delivery=replace(sender.delivery, outbox=cast("Any", gate))
    )
    now = int(time.time())
    await sender.send(item("batch-a"), now, 700001, targets(offline, online))
    await sender.send(item("batch-b"), now, 700002, targets(offline, online))
    assert not any(ident == offline.id for ident, _, _ in messenger.seen)
    assert [
        (name, unit) for ident, name, unit in messenger.seen if ident == online.id
    ] == [(name, unit) for name in _NAMES[:2] for unit in _STAGES]
    assert sender.ledger is not None
    with SqliteDatabase(sender.ledger.path).connect() as db:
        assert db.execute(
            "SELECT SUM(attempts),SUM(deadline_at) FROM stages "
            "WHERE target LIKE '%offline%'"
        ).fetchone() == (0, 0)
    from types import SimpleNamespace

    recovery = BiliDeliveryRecovery(
        sender,
        cast(
            "Any",
            SimpleNamespace(
                push_targets_for_dynamic=lambda _uid, **_kw: targets(offline, online)
            ),
        ),
        accounts=cast("Any", gate),
    )
    gate.ready.add(offline)
    await recovery("synthetic reconnect")
    await drain(owner)
    assert [
        (name, unit) for ident, name, unit in messenger.seen if ident == offline.id
    ] == [(name, unit) for name in _NAMES[:2] for unit in _STAGES]


@pytest.mark.asyncio
async def test_expired_uncertain_turn_releases_next_without_resetting_receipts(
    tmp_path: Path,
) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    owner = TaskOwner()
    messenger = QueueMessenger(
        failures={(target.id, "batch-a", "link"): [DeliveryFailureKind.UNCERTAIN]}
    )
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    now = int(time.time())
    await sender.send(item("batch-a"), now, 700001, targets(target))
    await sender.send(item("batch-b"), now, 700002, targets(target))
    assert messenger.seen == [(target.id, "batch-a", "link")]
    assert sender.ledger is not None
    with SqliteDatabase(sender.ledger.path).connect() as db:
        db.execute("UPDATE deliveries SET created=? WHERE id='batch-a'", (now - 86401,))
    wake_ready(sender)
    await drain(owner)
    assert sender.ledger.stage_state("batch-a", target, "link") == "uncertain"
    assert messenger.seen == [(target.id, "batch-a", "link")] + [
        (target.id, "batch-b", unit) for unit in _STAGES
    ]


@pytest.mark.asyncio
async def test_active_send_is_not_preempted_by_retention_expiry(tmp_path: Path) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "queue.sqlite")
    now = int(time.time())
    for name in _NAMES[:2]:
        ledger.prepare(item(name), now, 700001, targets(target), ())
    async with own_delivery(ledger, "batch-a"):
        assert ledger.queue_claim("batch-a", (target,)) == {target}
        assert ledger.claim("batch-a", target, "link")
        with SqliteDatabase(ledger.path).connect() as db:
            db.execute(
                "UPDATE deliveries SET created=? WHERE id='batch-a'", (now - 86401,)
            )
        assert ledger.queue_ready() == []
        ledger.finish(
            "batch-a", target, "link", SendResult(delivered=True, message_id="receipt")
        )
    assert [entry["item"]["id_str"] for entry in ledger.queue_ready()] == ["batch-b"]


@pytest.mark.asyncio
async def test_queued_permission_changes_are_rechecked(tmp_path: Path) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    owner = TaskOwner()
    messenger = QueueMessenger(gate=(target.id, "batch-a", "image"))
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    allowed = {700001, 700002, 700003}
    sender = replace(
        sender, stage_eligible=lambda _target, uid, _stage, _categories: uid in allowed
    )
    now = int(time.time())
    first = asyncio.ensure_future(
        sender.send(item("batch-a"), now, 700001, targets(target))
    )
    await asyncio.wait_for(messenger.entered.wait(), 5)
    await sender.send(item("batch-b"), now, 700002, targets(target))
    await sender.send(item("batch-c"), now, 700003, targets(target))
    allowed.remove(700002)
    messenger.release.set()
    await first
    await drain(owner)
    assert not any(name == "batch-b" for _, name, _ in messenger.seen)
    assert [(name, unit) for _, name, unit in messenger.seen] == [
        (name, unit) for name in ("batch-a", "batch-c") for unit in _STAGES
    ]


@pytest.mark.asyncio
async def test_competing_senders_cannot_claim_successor_or_repeat_units(
    tmp_path: Path,
) -> None:
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    owner = TaskOwner()
    messenger = QueueMessenger(gate=(target.id, "batch-a", "image"))
    path = tmp_path / "queue.sqlite"
    sender = sender_at(path, messenger, owner)
    rival = sender_at(path, messenger, owner)
    now = int(time.time())
    sender.enqueue(item("batch-a"), now, 700001, targets(target))
    sender.enqueue(item("batch-b"), now, 700002, targets(target))
    first = asyncio.ensure_future(
        sender.send(item("batch-a"), now, 700001, targets(target))
    )
    await asyncio.wait_for(messenger.entered.wait(), 5)
    await asyncio.gather(
        rival.send(item("batch-a"), now, 700001, targets(target), resume=True),
        rival.send(item("batch-b"), now, 700002, targets(target), resume=True),
    )
    assert not any(name == "batch-b" for _, name, _ in messenger.seen)
    messenger.release.set()
    await first
    await drain(owner)
    assert [(name, unit) for _, name, unit in messenger.seen] == [
        (name, unit) for name in _NAMES[:2] for unit in _STAGES
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("registration_fails", [False, True])
async def test_monitor_registers_before_spawning_and_releases_failed_claim(
    tmp_path: Path, *, registration_fails: bool
) -> None:
    from types import SimpleNamespace

    service = build_test_bilibili_service(tmp_path / "monitor")
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    owner = TaskOwner()
    messenger = QueueMessenger()
    sender = sender_at(tmp_path / "queue.sqlite", messenger, owner)
    service.spawn = owner.create
    service.targets = cast(
        "Any",
        SimpleNamespace(
            category_config_for_uid=lambda _uid: None,
            suppress_patterns_for_uid=lambda _uid: [],
            push_targets_for_dynamic=lambda _uid, **_kw: targets(target),
        ),
    )
    registered: list[str] = []
    failed = registration_fails

    def register(*args: Any) -> None:
        nonlocal failed
        if failed:
            failed = False
            message = "synthetic registration failure"
            raise OSError(message)
        sender.enqueue(*args)
        registered.append(args[0]["id_str"])

    async def send(*args: Any) -> None:
        assert args[0]["id_str"] in registered
        await sender.send(*args)

    service.register_delivery = register
    now = int(time.time())
    values = []
    checkpoints = {}
    for offset, name in enumerate(_NAMES[:2]):
        value = item(name)
        uid = 700001 + offset
        value["modules"]["module_author"]["mid"] = uid
        checkpoints[uid] = now - 1
        values.append((now + offset, value))
    if registration_fails:
        with pytest.raises(OSError, match="synthetic registration failure"):
            await _push_new_dynamics(service, values, checkpoints, send)
        assert not owner.tasks
    batch = await _push_new_dynamics(service, values, checkpoints, send)
    await asyncio.gather(*batch.delivery_tasks)
    await drain(owner)
    assert registered == list(_NAMES[:2])
    assert [(name, unit) for _, name, unit in messenger.seen] == [
        (name, unit) for name in _NAMES[:2] for unit in _STAGES
    ]
