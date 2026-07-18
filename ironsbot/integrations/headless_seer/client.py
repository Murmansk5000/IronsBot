# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging

from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.integrations.headless_seer.game import HeadlessStateNotifier, SeerGame

logger = logging.getLogger(__name__)


class ClientManager:
    """Manage the process-wide headless Seer game client."""

    def __init__(self) -> None:
        self._client: SeerGame | None = None
        self._login_lock = asyncio.Lock()

    def get_client(self) -> SeerGame:
        if self._client is None or self._client._impl is None:
            raise NotLoggedInError("Headless Seer client is not logged in")
        if not self._client._impl.is_connected or not self._client._is_logged_in:
            raise DisconnectedError("Headless Seer client is disconnected")
        return self._client

    async def login(
        self,
        user_id: int,
        password: str,
        login_server_url: str,
        *,
        heartbeat_interval: float | None = None,
        reconnect_retries: int = 0,
        reconnect_delay: float = 5.0,
        reconnect_delay_max: float = 120.0,
        state_notifier: HeadlessStateNotifier | None = None,
    ) -> SeerGame:
        async with self._login_lock:
            current = self._client
            if current is not None:
                if current.is_logged_in and int(current.user_id) == int(user_id):
                    logger.info(
                        "Headless Seer login reused existing client: %s",
                        user_id,
                    )
                    return current
                current.logout()

            game = SeerGame(
                user_id,
                password,
                login_server_url=login_server_url,
                heartbeat_interval=heartbeat_interval,
                reconnect_retries=reconnect_retries,
                reconnect_delay=reconnect_delay,
                reconnect_delay_max=reconnect_delay_max,
                state_notifier=state_notifier,
            )
            self._client = game
            try:
                await game.login()
                logger.info("Headless Seer client logged in: %s", user_id)
            except Exception:
                if reconnect_retries != 0:
                    logger.warning(
                        "Headless Seer initial login failed; reconnect scheduled",
                        exc_info=True,
                    )
                    game.schedule_reconnect()
                else:
                    if self._client is game:
                        self._client = None
                    raise
            return game

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.logout()
            logger.info("Headless Seer client disconnected")
            self._client = None
