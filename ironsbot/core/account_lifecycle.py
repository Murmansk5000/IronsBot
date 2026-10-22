# SPDX-License-Identifier: MIT
"""Connection observations shared by protocol adapters and the application."""

from typing import Protocol

from ironsbot.core.platform import BotAccountRef


class BotConnectionObserver(Protocol):
    async def bot_connect(self, account: BotAccountRef) -> None: ...

    async def bot_disconnect(self, account: BotAccountRef) -> None: ...
