# SPDX-License-Identifier: MIT
"""Cancellation-safe wakeups for durable conversation queue heads."""

from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import fields
from typing import TYPE_CHECKING, Any

from ironsbot.core.platform import ConversationRef, Platform, reference_digest
from ironsbot.services.bilibili.delivery_lifecycle import (
    has_pending_workers,
    own_delivery,
)
from ironsbot.services.bilibili.delivery_targets import canonical_targets
from ironsbot.services.bilibili.revisions import delivery_key
from ironsbot.services.bilibili.target_models import BiliPushTargets

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.bilibili.outbound_delivery import (
        BilibiliDynamicOutboundSender,
    )

_LOGGER = logging.getLogger(__name__)
_WAKES: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[str, str], asyncio.Future[None]]
] = weakref.WeakKeyDictionary()


async def submit_delivery(
    sender: BilibiliDynamicOutboundSender, entry: dict[str, Any], *, resume: bool
) -> None:
    item, pub_ts, uid = entry["item"], entry["pub_ts"], entry["uid"]
    targets = canonical_targets(sender.delivery.private_routes, entry["targets"])
    categories = tuple(entry["categories"])
    sender.enqueue(item, pub_ts, uid, targets, categories)
    if sender.ledger is None:
        await sender._send_owned(item, pub_ts, uid, targets, categories, resume=resume)
        return
    if resume:
        sender.ledger.queue_wake(delivery_key(item), conversations(targets))
    await sender.send_queued({**entry, "targets": targets})


def conversations(targets: BiliPushTargets) -> tuple[ConversationRef, ...]:
    return tuple(
        dict.fromkeys(
            target
            for field in fields(targets)
            for target in getattr(targets, field.name)
        )
    )


def selected_targets(
    targets: BiliPushTargets, allowed: Iterable[ConversationRef]
) -> BiliPushTargets:
    selected = frozenset(allowed)
    return BiliPushTargets(
        **{
            field.name: [
                target for target in getattr(targets, field.name) if target in selected
            ]
            for field in fields(targets)
        }
    )


def entry_targets(entry: dict[str, Any]) -> BiliPushTargets:
    return BiliPushTargets(
        **{
            name: [
                ConversationRef(
                    Platform(raw["platform"]),
                    raw["kind"],
                    raw["id"],
                    account_id=raw["account_id"],
                )
                for raw in targets
            ]
            for name, targets in entry["targets"].items()
        }
    )


def wake_ready(sender: BilibiliDynamicOutboundSender) -> None:
    ledger = sender.ledger
    if ledger is None:
        return
    pending = _WAKES.setdefault(asyncio.get_running_loop(), {})
    try:
        ready = ledger.queue_ready()
    except Exception as error:  # noqa: BLE001 - a wakeup cannot change a send receipt
        _LOGGER.warning(
            "Bilibili queue wake deferred: exception=%s", type(error).__name__
        )
        return
    for entry in ready:
        dynamic_id = delivery_key(entry["item"])
        key = (str(ledger.path.resolve()), dynamic_id)
        if key in pending:
            continue
        operation = sender.send_queued(entry)
        task = (
            sender.spawn(operation, name="bilibili.queue.head")
            if sender.spawn
            else asyncio.ensure_future(operation)
        )
        pending[key] = task

        def finished(
            result: asyncio.Future[None], *, key: tuple[str, str] = key
        ) -> None:
            if pending.get(key) is result:
                del pending[key]
            if not result.cancelled() and result.exception() is not None:
                _LOGGER.warning(
                    "Bilibili queued delivery deferred: dynamic=%s exception=%s",
                    key[1],
                    type(result.exception()).__name__,
                )
            elif not result.cancelled():
                wake_ready(sender)

        task.add_done_callback(finished)


def log_turn(dynamic_id: str, target: ConversationRef, state: str) -> None:
    _LOGGER.info(
        "Bilibili conversation queue: dynamic=%s target=%s state=%s",
        dynamic_id,
        reference_digest(target.id),
        state,
    )


def available_turns(
    sender: BilibiliDynamicOutboundSender,
    dynamic_id: str,
    claimed: set[ConversationRef],
) -> set[ConversationRef]:
    ledger = sender.ledger
    assert ledger is not None
    accounts, routes = sender.delivery.outbox, sender.delivery.private_routes
    ready = set()
    for target in claimed:
        decision = routes.decision_for(target) if routes else None
        if decision is not None and (
            decision.status == "skipped" or decision.target != target
        ):
            for stage in ("link", "text", "image"):
                ledger.skip_stage(dynamic_id, target, stage)
            ledger.queue_settle(dynamic_id, target)
            log_turn(dynamic_id, target, "routing_changed_or_skipped")
        elif (decision is not None and decision.status == "unavailable") or (
            accounts is not None and not accounts.account_ready(target)
        ):
            ledger.queue_wait_account(dynamic_id, target)
            log_turn(dynamic_id, target, "waiting_for_route_or_account")
        else:
            ready.add(target)
    return ready


def settle_turn(
    sender: BilibiliDynamicOutboundSender,
    dynamic_id: str,
    target: ConversationRef,
    *,
    final: bool = False,
) -> None:
    ledger = sender.ledger
    if (
        ledger is not None
        and not has_pending_workers(target)
        and ledger.queue_settle(dynamic_id, target, final=final)
    ):
        log_turn(dynamic_id, target, "finished")
        wake_ready(sender)


async def dispatch_entry(
    sender: BilibiliDynamicOutboundSender, entry: dict[str, Any]
) -> None:
    ledger = sender.ledger
    assert ledger is not None
    item = entry["item"]
    dynamic_id = delivery_key(item)
    targets = (
        entry["targets"]
        if isinstance(entry["targets"], BiliPushTargets)
        else entry_targets(entry)
    )
    entry = ledger.queue_entry(dynamic_id)
    item = entry["item"]
    async with own_delivery(
        ledger, dynamic_id, on_release=lambda: wake_ready(sender)
    ) as owned:
        if owned:
            claimed = ledger.queue_claim(dynamic_id, conversations(targets))
            claimed = available_turns(sender, dynamic_id, claimed)
            if not claimed:
                for target in conversations(targets):
                    log_turn(dynamic_id, target, "waiting_for_predecessor_or_recovery")
            else:
                try:
                    await sender._send_owned(
                        item,
                        entry["pub_ts"],
                        entry["uid"],
                        selected_targets(targets, claimed),
                        tuple(entry["categories"]),
                        resume=True,
                    )
                finally:
                    for target in claimed:
                        settle_turn(sender, dynamic_id, target, final=True)
    wake_ready(sender)
