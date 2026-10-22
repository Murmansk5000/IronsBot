# SPDX-License-Identifier: MIT
"""Best-effort display identity; never infer a task bot from notice routing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.integrations.onebot.connections import OneBotConnections

from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import Platform

_TTL = 600


@dataclass(slots=True)
class OneBotExecutionIdentityResolver:
    connections: OneBotConnections
    account_name: Callable[[str], str]
    _names: dict[str, tuple[float, object, str]] = field(
        default_factory=dict, init=False, repr=False
    )

    async def resolve(self, identity: ExecutionIdentity) -> ExecutionIdentity:
        if identity.platform is not Platform.ONEBOT:
            return identity
        bot = self.connections.get(identity.account_id)
        cached_at, source, nickname = self._names.get(
            identity.account_id, (0.0, None, "")
        )
        if source is not bot or monotonic() - cached_at >= _TTL or not nickname:
            nickname = ""
            if bot is not None:
                try:
                    response = await asyncio.wait_for(
                        bot.call_api("get_login_info"), timeout=2
                    )
                    if self.connections.get(identity.account_id) is bot and isinstance(
                        response, dict
                    ):
                        nickname = str(response.get("nickname") or "").strip()
                        if nickname:
                            self._names[identity.account_id] = (
                                monotonic(),
                                bot,
                                nickname,
                            )
                except Exception:  # noqa: BLE001 - nickname is not required for delivery
                    pass
        configured = self.account_name(identity.account_id)
        name = nickname or (
            configured
            if configured != identity.account_id
            else identity.display_name or configured
        )
        return ExecutionIdentity(identity.platform, identity.account_id, name)
