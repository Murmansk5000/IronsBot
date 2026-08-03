# SPDX-License-Identifier: MIT
"""Short-lived isolated headless Seer sessions for trusted extensions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.operations.headless import (
    HeadlessClient,
    HeadlessGame,
    HeadlessLoginRequest,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from ironsbot.config.models.operations import HeadlessConfig


DEDICATED_SESSION_LOGIN_INCOMPLETE = "dedicated headless login did not complete"


async def _ignore_session_state(**_kwargs: object) -> None:
    """Dedicated one-off sessions must not change the shared headless state."""


class HeadlessSessionFactory:
    """Create a short-lived Seer session without replacing the shared client."""

    def __init__(
        self,
        client_factory: Callable[[], HeadlessClient],
        connection: HeadlessConfig,
        *,
        request_interval_seconds: float = 0.0,
    ) -> None:
        self._client_factory = client_factory
        self._connection = connection
        self._request_interval_seconds = max(request_interval_seconds, 0.0)
        self._active_sessions: dict[str, int] = {}

    @property
    def active_session_count(self) -> int:
        return sum(self._active_sessions.values())

    @property
    def active_sessions_by_label(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._active_sessions))

    @asynccontextmanager
    async def open(
        self,
        *,
        user_id: int,
        password: str,
        label: str = "extension",
    ) -> AsyncIterator[HeadlessGame]:
        """Log in a dedicated account once and always disconnect afterwards."""

        client = self._client_factory()
        online = False
        normalized_label = label.strip() or "extension"
        try:
            game = await client.login(
                HeadlessLoginRequest(
                    user_id=user_id,
                    password=password,
                    login_server_url=self._connection.login_server_addr,
                    heartbeat_interval=self._connection.heartbeat_interval,
                    request_timeout_seconds=self._connection.request_timeout_seconds,
                    reconnect_retries=0,
                    reconnect_delay=self._connection.reconnect_delay,
                    reconnect_delay_max=self._connection.reconnect_delay_max,
                    state_notifier=_ignore_session_state,
                    request_interval_seconds=self._request_interval_seconds,
                )
            )
            if not game.is_logged_in:
                raise RuntimeError(DEDICATED_SESSION_LOGIN_INCOMPLETE)
            self._active_sessions[normalized_label] = (
                self._active_sessions.get(normalized_label, 0) + 1
            )
            online = True
            yield game
        finally:
            if online:
                remaining = self._active_sessions[normalized_label] - 1
                if remaining > 0:
                    self._active_sessions[normalized_label] = remaining
                else:
                    self._active_sessions.pop(normalized_label, None)
            client.shutdown()
