# SPDX-License-Identifier: MIT
"""Observed transport addresses do not grant permissions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.identity_principals import IdentityPrincipalService


@dataclass(frozen=True, slots=True)
class OfficialAddress:
    app_id: str
    openid: str
    member_seen: bool
    private_seen: bool
    member_seen_at: float | None = None
    private_seen_at: float | None = None


class OfficialAddressStore(Protocol):
    async def observe(
        self, identity: OfficialIdentity, *, now: float
    ) -> OfficialAddress: ...
    async def all_addresses(self) -> tuple[OfficialAddress, ...]: ...


@dataclass(slots=True)
class OfficialAddressService:
    store: OfficialAddressStore
    principals: IdentityPrincipalService
    on_private_link: Callable[[CrossPlatformIdentityLink], None]
    on_private_unlink: Callable[[CrossPlatformIdentityLink], None]
    _addresses: dict[tuple[str, str], OfficialAddress] = field(default_factory=dict)
    _private_links: dict[tuple[str, str], CrossPlatformIdentityLink] = field(
        default_factory=dict
    )
    _configured: set[tuple[str, str]] = field(default_factory=set)

    def configure_private(self, app_id: str, openid: str) -> None:
        self._configured.add((app_id, openid))

    def accept_link(self, link: CrossPlatformIdentityLink) -> None:
        if link.official.kind == "user":
            key = (link.official.app_id, link.official.openid)
            old = self._addresses.get(key)
            self._addresses[key] = OfficialAddress(
                *key,
                member_seen=old.member_seen if old else False,
                private_seen=True,
                member_seen_at=old.member_seen_at if old else None,
                private_seen_at=link.linked_at,
            )
        self.refresh()

    async def load(self, links: tuple[CrossPlatformIdentityLink, ...]) -> None:
        for address in await self.store.all_addresses():
            self._addresses[(address.app_id, address.openid)] = address
        for link in links:
            address = await self.store.observe(link.official, now=link.linked_at)
            self._addresses[(address.app_id, address.openid)] = address
        self.refresh()

    async def observe(self, incoming: IncomingMessageRef) -> None:
        actor = incoming.actor
        if actor.platform is not Platform.QQ_OFFICIAL or actor.account_id is None:
            return
        if actor.kind not in {"user", "member"}:
            return
        address = await self.store.observe(
            OfficialIdentity(actor.account_id, actor.kind, actor.id),
            now=time.time(),
        )
        self._addresses[(address.app_id, address.openid)] = address
        self.refresh()

    def refresh(self) -> None:
        for key in self._addresses.keys() | self._configured:
            address = self._addresses.get(key)
            if key not in self._configured and (
                address is None or not address.private_seen
            ):
                continue
            app_id, openid = key
            principal = self.principals.actor_principal(
                ActorRef(Platform.QQ_OFFICIAL, openid, account_id=app_id)
            )
            previous = self._private_links.get(key)
            qq_id = principal.id if principal.kind == "qq" else None
            if previous is not None and previous.onebot_qq_id != qq_id:
                self.on_private_unlink(previous)
                del self._private_links[key]
            if qq_id is not None and (
                previous is None or previous.onebot_qq_id != qq_id
            ):
                link = CrossPlatformIdentityLink(
                    qq_id,
                    OfficialIdentity(app_id, "user", openid),
                    (address.private_seen_at or 0) if address is not None else 0,
                )
                self.on_private_link(link)
                self._private_links[key] = link
