# SPDX-License-Identifier: MIT
"""Resume only original target stages never attempted before this process."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.services.bilibili.target_models import BiliPushTargets

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.outbound_delivery import (
        BilibiliDynamicOutboundSender,
    )
    from ironsbot.services.bilibili.targets import BiliTargetService


@dataclass(slots=True)
class BiliStartupRecovery:
    sender: BilibiliDynamicOutboundSender
    targets: BiliTargetService
    _connections: set[str] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        # Recover before any connection or polling task can start new sends.
        if self.sender.ledger is not None:
            self.sender.ledger.recover()

    async def __call__(self, connection_key: str = "startup") -> None:
        async with self._lock:
            if connection_key in self._connections or self.sender.ledger is None:
                return
            ledger = self.sender.ledger
            self._connections.add(connection_key)
            for entry in ledger.pending():
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
                    ]

                selected = BiliPushTargets(
                    full_group_conversations=retained("full_group_conversations"),
                    link_group_conversations=retained("link_group_conversations"),
                    full_private_conversations=retained("full_private_conversations"),
                    link_private_conversations=retained("link_private_conversations"),
                )
                try:
                    await self.sender.send(
                        entry["item"],
                        entry["pub_ts"],
                        entry["uid"],
                        selected,
                        categories,
                        resume=True,
                    )
                except Exception:
                    _LOGGER.exception(
                        "Bilibili startup recovery failed: dynamic=%s",
                        entry["item"].get("id_str"),
                    )
