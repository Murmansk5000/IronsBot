# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging

from ironsbot.core.tasks import TaskSpawner
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.services.operations.headless import HeadlessLoginRequest
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)

logger = logging.getLogger(__name__)


class ClientManager:
    """Manage the process-wide headless Seer game client."""

    def __init__(self, spawn: TaskSpawner) -> None:
        self._client: SeerGame | None = None
        self._login_lock = asyncio.Lock()
        self._operations = HeadlessOperationTracker()
        self._spawn = spawn

    def get_client(self) -> SeerGame:
        if self._client is None or self._client._impl is None:
            raise NotLoggedInError("Headless Seer client is not logged in")
        if not self._client._impl.is_connected or not self._client._is_logged_in:
            raise DisconnectedError("Headless Seer client is disconnected")
        return self._client

    async def login(self, request: HeadlessLoginRequest) -> SeerGame:
        async with self._login_lock:
            current = self._client
            if current is not None:
                if (
                    current.is_logged_in
                    and int(current.user_id) == request.user_id
                ):
                    logger.info(
                        "Headless Seer login reused existing client: %s",
                        request.user_id,
                    )
                    return current
                current.logout()

            game = SeerGame(
                request.user_id,
                request.password,
                login_server_url=request.login_server_url,
                heartbeat_interval=request.heartbeat_interval,
                request_timeout_seconds=request.request_timeout_seconds,
                reconnect_retries=request.reconnect_retries,
                reconnect_delay=request.reconnect_delay,
                reconnect_delay_max=request.reconnect_delay_max,
                request_interval_seconds=request.request_interval_seconds,
                state_notifier=request.state_notifier,
                operations=self._operations,
                spawn=self._spawn,
            )
            self._client = game
            try:
                await game.login()
                logger.info(
                    "Headless Seer client logged in: %s",
                    request.user_id,
                )
            except Exception:
                if request.reconnect_retries != 0:
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
