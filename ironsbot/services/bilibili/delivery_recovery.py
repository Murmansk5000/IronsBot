# SPDX-License-Identifier: MIT
"""Resume original targets' safe unfinished units without resetting retry budgets."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.services.bilibili.target_models import BiliPushTargets

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.outbound_delivery import (
        BilibiliDynamicOutboundSender,
    )
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.messaging.delivery_tasks import DeliveryTaskStore


@dataclass(slots=True)
class BiliDeliveryRecovery:
    sender: BilibiliDynamicOutboundSender
    targets: BiliTargetService
    notify: Callable[[str, str], Awaitable[None]] | None = None
    accounts: DeliveryTaskStore | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        # Recover before any connection or polling task can start new sends.
        if self.sender.ledger is not None:
            self.sender.ledger.recover()

    async def __call__(self, connection_key: str = "startup") -> None:
        _LOGGER.debug("Bilibili recovery triggered: source=%s", connection_key)
        async with self._lock:
            if self.sender.ledger is None:
                return
            ledger = self.sender.ledger
            for entry in ledger.pending():
                dynamic_id = str(entry["item"].get("id_str", ""))
                before = ledger.state_counts(dynamic_id)
                categories = tuple(entry["categories"])
                current = self.targets.push_targets_for_dynamic(
                    entry["uid"], categories=categories
                )
                allowed = {
                    (value["platform"], value["kind"], value["id"], value["account_id"])
                    for values in entry["targets"].values()
                    for value in values
                }

                def retained(
                    name: str,
                    current: BiliPushTargets = current,
                    allowed: set[tuple[str, str, str, str | None]] = allowed,
                ) -> list[ConversationRef]:
                    return [
                        target
                        for target in getattr(current, name)
                        if (
                            target.platform.value,
                            target.kind,
                            target.id,
                            target.account_id,
                        )
                        in allowed
                        and (
                            self.accounts is None or self.accounts.account_ready(target)
                        )
                    ]

                selected = BiliPushTargets(
                    full_group_conversations=retained("full_group_conversations"),
                    link_group_conversations=retained("link_group_conversations"),
                    full_private_conversations=retained("full_private_conversations"),
                    link_private_conversations=retained("link_private_conversations"),
                )
                try:
                    if not selected.has_targets:
                        await self._report(dynamic_id, before)
                        continue
                    await self.sender.send(
                        entry["item"],
                        entry["pub_ts"],
                        entry["uid"],
                        selected,
                        categories,
                        resume=True,
                    )
                    self._backoff(dynamic_id, selected)
                    await self._report(dynamic_id, before)
                except Exception:
                    _LOGGER.exception(
                        "Bilibili recovery failed: dynamic=%s",
                        entry["item"].get("id_str"),
                    )

    def _backoff(self, dynamic_id: str, selected: BiliPushTargets) -> None:
        if self.accounts is None or self.sender.ledger is None:
            return
        targets = {
            *selected.full_group_conversations,
            *selected.link_group_conversations,
            *selected.full_private_conversations,
            *selected.link_private_conversations,
        }
        failed_accounts: set[tuple[str, str | None]] = set()
        for target, _stage, result in self.sender.ledger.failures(dynamic_id):
            account = (target.platform.value, target.account_id)
            if (
                target in targets
                and account not in failed_accounts
                and result.failure_kind
                in {
                    DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                    DeliveryFailureKind.RETRYABLE,
                }
            ):
                self.accounts.account_failed(target)
                failed_accounts.add(account)

    async def _report(self, dynamic_id: str, before: dict[str, int]) -> None:
        ledger = self.sender.ledger
        if ledger is None or self.notify is None:
            return
        counts = ledger.state_counts(dynamic_id)
        unresolved = any(
            counts.get(key, 0) for key in ("waiting", "retry", "failed", "uncertain")
        )
        if not (unresolved or before.get("waiting", 0) or before.get("retry", 0)):
            return
        if ledger.claim_recovery_report(dynamic_id, counts):
            labels = {
                "waiting": "等待恢复",
                "retry": "正在重试",
                "failed": "永久失败或预算耗尽",
                "uncertain": "结果不确定，待确认",
                "success": "已送达",
            }
            await self.notify(
                dynamic_id,
                f"B站推送恢复状态\n动态ID：{dynamic_id}\n"
                + "\n".join(
                    f"{label}：{counts[key]}"
                    for key, label in labels.items()
                    if counts.get(key)
                ),
            )
