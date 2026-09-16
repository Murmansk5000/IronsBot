# SPDX-License-Identifier: MIT
"""Silent, conservative correlation of official group members to QQ IDs."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.outbound import TextPart
from ironsbot.core.platform import Platform, reference_digest
from ironsbot.services.identity_link_store import (
    IdentityLinkConflictError,
    OfficialIdentity,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.identity_link_store import IdentityLinkStore

_SPACE_PATTERN = re.compile(r"\s+")
_MIN_CONFIRMATIONS = 2
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IdentityObservationAccount:
    app_id: str
    trusted_onebot_sender_id: int
    groups: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class OneBotReplyObservation:
    sender_id: int
    group_id: int
    mentioned_qq_ids: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class _PendingReply:
    token: int
    official: OfficialIdentity
    onebot_group_id: int
    text: str
    created_at: float
    source_message_id: str


@dataclass(slots=True)
class SilentIdentityObservationService:
    store: IdentityLinkStore
    accounts: Mapping[str, IdentityObservationAccount]
    confirmation_count: int = 2
    match_window_seconds: float = 10.0
    clock: Callable[[], float] = time.time
    _pending: list[_PendingReply] = field(default_factory=list, init=False)
    _confirmations: dict[tuple[OfficialIdentity, str], set[str]] = field(
        default_factory=dict,
        init=False,
    )
    _next_token: int = field(default=1, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        if self.confirmation_count < _MIN_CONFIRMATIONS:
            msg = "silent identity observation requires at least two confirmations"
            raise ValueError(msg)
        if self.match_window_seconds <= 0:
            msg = "identity observation match window must be positive"
            raise ValueError(msg)
        self.accounts = dict(self.accounts)

    def record_official_reply(
        self,
        incoming: IncomingMessageRef,
        message: OutboundMessage,
    ) -> int | None:
        if (
            incoming.platform is not Platform.QQ_OFFICIAL
            or incoming.conversation.kind != "group"
            or incoming.actor.kind != "member"
            or incoming.actor.scope_id != incoming.conversation.id
            or incoming.actor.account_id is None
        ):
            return None
        account = self.accounts.get(incoming.actor.account_id)
        if account is None:
            return None
        onebot_group_id = account.groups.get(incoming.conversation.id)
        text = _outbound_text(message)
        if onebot_group_id is None or not text:
            return None
        now = self.clock()
        self._prune(now)
        token = self._next_token
        self._next_token += 1
        self._pending.append(
            _PendingReply(
                token,
                OfficialIdentity(
                    incoming.actor.account_id,
                    "member",
                    incoming.actor.id,
                    incoming.conversation.id,
                ),
                onebot_group_id,
                text,
                now,
                incoming.message_id,
            )
        )
        return token

    def discard_official_reply(self, token: int | None) -> None:
        if token is None:
            return
        self._pending = [item for item in self._pending if item.token != token]

    async def observe_onebot(self, observation: OneBotReplyObservation) -> bool:
        now = self.clock()
        self._prune(now)
        match = self._match_onebot(observation, now=now)
        if match is None:
            return False
        matched, qq_id = match
        self.discard_official_reply(matched.token)
        key = (matched.official, qq_id)
        async with self._lock:
            existing = await self.store.for_official(matched.official)
            if existing is not None:
                return existing.onebot_qq_id == qq_id
            confirmations = self._confirmations.setdefault(key, set())
            confirmations.add(matched.source_message_id)
            if len(confirmations) < self.confirmation_count:
                return False
            try:
                await self.store.link_verified(
                    onebot_qq_id=qq_id,
                    official=matched.official,
                    now=now,
                )
            except IdentityLinkConflictError:
                _LOGGER.warning(
                    "silent identity link conflict: app=%s member=%s",
                    reference_digest(matched.official.app_id),
                    reference_digest(matched.official.openid),
                )
                return False
            self._confirmations.pop(key, None)
        _LOGGER.info(
            "silent identity link confirmed: app=%s member=%s qq=%s",
            reference_digest(matched.official.app_id),
            reference_digest(matched.official.openid),
            reference_digest(qq_id),
        )
        return True

    def _match_onebot(
        self,
        observation: OneBotReplyObservation,
        *,
        now: float,
    ) -> tuple[_PendingReply, str] | None:
        account = next(
            (
                value
                for value in self.accounts.values()
                if value.trusted_onebot_sender_id == observation.sender_id
            ),
            None,
        )
        if account is None:
            return None
        mentioned = observation.mentioned_qq_ids
        text = _normalize_text(observation.text)
        if len(mentioned) != 1 or not text:
            return None
        matches = [
            item
            for item in self._pending
            if item.official.app_id == account.app_id
            and item.onebot_group_id == observation.group_id
            and item.text == text
            and now - item.created_at <= self.match_window_seconds
        ]
        if len(matches) != 1:
            return None
        return matches[0], mentioned[0]

    def _prune(self, now: float) -> None:
        cutoff = now - self.match_window_seconds
        self._pending = [item for item in self._pending if item.created_at >= cutoff]


def _outbound_text(message: OutboundMessage) -> str:
    return _normalize_text(
        "".join(part.text for part in message.parts if isinstance(part, TextPart))
    )


def _normalize_text(text: str) -> str:
    return _SPACE_PATTERN.sub(" ", text).strip()
