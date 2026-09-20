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
    CrossPlatformGroupLink,
    GroupLinkConflictError,
    IdentityLinkConflictError,
    OfficialIdentity,
    canonical_official_identity,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.identity_link_store import IdentityLinkStore

_SPACE_PATTERN = re.compile(r"\s+")
_MIN_CONFIRMATIONS = 1
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IdentityObservationAccount:
    app_id: str
    trusted_onebot_sender_id: int
    groups: dict[str, int]
    candidate_onebot_group_ids: frozenset[int] = frozenset()


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
    official_group_openid: str
    onebot_group_id: int | None
    text: str
    created_at: float
    source_message_id: str


@dataclass(slots=True)
class SilentIdentityObservationService:
    store: IdentityLinkStore
    accounts: Mapping[str, IdentityObservationAccount]
    confirmation_count: int = 1
    match_window_seconds: float = 10.0
    clock: Callable[[], float] = time.time
    on_link: Callable[[str, OfficialIdentity], None] | None = None
    on_group_link: Callable[[CrossPlatformGroupLink], None] | None = None
    _pending: list[_PendingReply] = field(default_factory=list, init=False)
    _confirmations: dict[tuple[OfficialIdentity, str], set[str]] = field(
        default_factory=dict,
        init=False,
    )
    _next_token: int = field(default=1, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        if self.confirmation_count < _MIN_CONFIRMATIONS:
            msg = "silent identity observation requires at least one confirmation"
            raise ValueError(msg)
        if self.match_window_seconds <= 0:
            msg = "identity observation match window must be positive"
            raise ValueError(msg)
        self.accounts = dict(self.accounts)

    def register_group_link(self, link: CrossPlatformGroupLink) -> None:
        account = self.accounts.get(link.official_app_id)
        if account is None:
            return
        account.groups[link.official_group_openid] = int(link.onebot_group_id)

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
        if not text or (
            onebot_group_id is None and not account.candidate_onebot_group_ids
        ):
            return None
        now = self.clock()
        self._prune(now)
        token = self._next_token
        self._next_token += 1
        self._pending.append(
            _PendingReply(
                token,
                canonical_official_identity(
                    OfficialIdentity(
                        incoming.actor.account_id,
                        "member",
                        incoming.actor.id,
                        incoming.conversation.id,
                    )
                ),
                incoming.conversation.id,
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
        group_discovered = False
        async with self._lock:
            if matched.onebot_group_id is None:
                try:
                    group_link = await self.store.link_group_verified(
                        onebot_group_id=str(observation.group_id),
                        official_app_id=matched.official.app_id,
                        official_group_openid=matched.official_group_openid,
                        now=now,
                    )
                except GroupLinkConflictError:
                    _LOGGER.warning(
                        "silent group link conflict: app=%s group=%s",
                        reference_digest(matched.official.app_id),
                        reference_digest(matched.official_group_openid),
                    )
                    return False
                self.register_group_link(group_link)
                if self.on_group_link is not None:
                    self.on_group_link(group_link)
                group_discovered = True
                _LOGGER.info(
                    "silent group link confirmed: app=%s group=%s onebot_group=%s",
                    reference_digest(group_link.official_app_id),
                    reference_digest(group_link.official_group_openid),
                    reference_digest(group_link.onebot_group_id),
                )
            if qq_id is None:
                return group_discovered
            return await self._link_member(matched, qq_id=qq_id, now=now)

    async def _link_member(
        self,
        pending: _PendingReply,
        *,
        qq_id: str,
        now: float,
    ) -> bool:
        existing = await self.store.for_official(pending.official)
        if existing is not None:
            return existing.onebot_qq_id == qq_id
        key = (pending.official, qq_id)
        confirmations = self._confirmations.setdefault(key, set())
        confirmations.add(pending.source_message_id)
        if len(confirmations) < self.confirmation_count:
            return False
        try:
            link = await self.store.link_verified(
                onebot_qq_id=qq_id,
                official=pending.official,
                now=now,
            )
        except IdentityLinkConflictError:
            _LOGGER.warning(
                "silent identity link conflict: app=%s member=%s",
                reference_digest(pending.official.app_id),
                reference_digest(pending.official.openid),
            )
            return False
        if self.on_link is not None:
            self.on_link(link.onebot_qq_id, link.official)
        self._confirmations.pop(key, None)
        _LOGGER.info(
            "silent identity link confirmed: app=%s member=%s qq=%s",
            reference_digest(pending.official.app_id),
            reference_digest(pending.official.openid),
            reference_digest(qq_id),
        )
        return True

    def _match_onebot(
        self,
        observation: OneBotReplyObservation,
        *,
        now: float,
    ) -> tuple[_PendingReply, str | None] | None:
        accounts = [
            value
            for value in self.accounts.values()
            if value.trusted_onebot_sender_id == observation.sender_id
        ]
        if len(accounts) != 1:
            return None
        account = accounts[0]
        mentioned = observation.mentioned_qq_ids
        text = _normalize_text(observation.text)
        if not text:
            return None
        matches = [
            item
            for item in self._pending
            if item.official.app_id == account.app_id
            and (
                item.onebot_group_id == observation.group_id
                or (
                    item.onebot_group_id is None
                    and observation.group_id in account.candidate_onebot_group_ids
                )
            )
            and item.text == text
            and now - item.created_at <= self.match_window_seconds
        ]
        if len(matches) != 1:
            return None
        return matches[0], mentioned[0] if len(mentioned) == 1 else None

    def _prune(self, now: float) -> None:
        cutoff = now - self.match_window_seconds
        self._pending = [item for item in self._pending if item.created_at >= cutoff]


def _outbound_text(message: OutboundMessage) -> str:
    return _normalize_text(
        "".join(part.text for part in message.parts if isinstance(part, TextPart))
    )


def _normalize_text(text: str) -> str:
    return _SPACE_PATTERN.sub(" ", text).strip()
