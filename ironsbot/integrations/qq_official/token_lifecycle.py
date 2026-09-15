# SPDX-License-Identifier: MIT
"""Redacted lifecycle evidence for SDK-owned QQ access tokens."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qqbot_agent_sdk.api_client import QQApiClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QQOfficialTokenObserver:
    """Observe token changes without retaining or logging the credential."""

    account: str
    _fingerprint: bytes | None = field(default=None, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    async def ensure(self, api: QQApiClient) -> str:
        token = await api.ensure_token()
        self.observe(token)
        return token

    def ensure_sync(self, api: QQApiClient) -> str:
        token = api.ensure_token_sync()
        self.observe(token)
        return token

    def observe(self, token: str | None) -> None:
        if not token:
            return
        fingerprint = hashlib.sha256(token.encode("utf-8")).digest()
        with self._lock:
            if fingerprint == self._fingerprint:
                return
            event = "acquired" if self._fingerprint is None else "refreshed"
            self._fingerprint = fingerprint
        logger.info(
            "QQ Official access token %s: account=%s",
            event,
            self.account,
        )
