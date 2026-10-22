# SPDX-License-Identifier: MIT
"""Application-owned live OneBot connections, independent of framework globals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class OneBotConnection(Protocol):
    """Return successful action data; raise protocol or transport failures."""

    self_id: str

    async def call_api(self, api: str, **data: Any) -> object: ...


class OneBotEventHandler(Protocol):
    async def __call__(
        self, connection: OneBotConnection, payload: dict[str, Any]
    ) -> None: ...


@dataclass(slots=True)
class OneBotConnections:
    _bots: dict[str, OneBotConnection] = field(
        default_factory=dict, init=False, repr=False
    )

    def connect(self, bot: OneBotConnection) -> None:
        self._bots[str(bot.self_id)] = bot

    def disconnect(self, bot: OneBotConnection) -> bool:
        account_id = str(bot.self_id)
        if self._bots.get(account_id) is bot:
            del self._bots[account_id]
            return True
        return False

    def get(self, account_id: str) -> OneBotConnection | None:
        return self._bots.get(account_id)

    def snapshot(
        self, *, preferred_id: str | None = None
    ) -> tuple[OneBotConnection, ...]:
        return tuple(
            sorted(
                self._bots.values(), key=lambda bot: str(bot.self_id) != preferred_id
            )
        )

    def clear(self) -> None:
        self._bots.clear()
