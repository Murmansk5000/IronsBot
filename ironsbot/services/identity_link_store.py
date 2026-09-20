# SPDX-License-Identifier: MIT
"""Persistence contract and records for explicit cross-platform identity links."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorKind


class IdentityLinkStoreError(RuntimeError):
    pass


class IdentityLinkChallengeInvalidError(IdentityLinkStoreError):
    pass


class IdentityLinkChallengeExpiredError(IdentityLinkStoreError):
    pass


class IdentityLinkConflictError(IdentityLinkStoreError):
    def __init__(self, existing_qq_id: str) -> None:
        self.existing_qq_id = existing_qq_id
        super().__init__("official identity is already linked")


class GroupLinkConflictError(IdentityLinkStoreError):
    def __init__(self) -> None:
        super().__init__("group identity is already linked")


@dataclass(frozen=True, slots=True)
class OfficialIdentity:
    app_id: str
    kind: ActorKind
    openid: str
    scope_id: str = ""


def canonical_official_identity(identity: OfficialIdentity) -> OfficialIdentity:
    """Return the stable principal key used for cross-platform links."""

    if identity.kind != "member" or not identity.scope_id:
        return identity
    return OfficialIdentity(
        app_id=identity.app_id,
        kind=identity.kind,
        openid=identity.openid,
    )


@dataclass(frozen=True, slots=True)
class CrossPlatformIdentityLink:
    onebot_qq_id: str
    official: OfficialIdentity
    linked_at: float


@dataclass(frozen=True, slots=True)
class CrossPlatformGroupLink:
    onebot_group_id: str
    official_app_id: str
    official_group_openid: str
    linked_at: float


class IdentityLinkStore(Protocol):
    async def link_group_verified(
        self,
        *,
        onebot_group_id: str,
        official_app_id: str,
        official_group_openid: str,
        now: float,
    ) -> CrossPlatformGroupLink: ...

    async def all_group_links(self) -> tuple[CrossPlatformGroupLink, ...]: ...

    async def issue(
        self,
        *,
        token_hash: str,
        onebot_qq_id: str,
        official_app_id: str,
        created_at: float,
        expires_at: float,
    ) -> None: ...

    async def consume(
        self,
        *,
        token_hash: str,
        official: OfficialIdentity,
        now: float,
    ) -> CrossPlatformIdentityLink: ...

    async def link_verified(
        self,
        *,
        onebot_qq_id: str,
        official: OfficialIdentity,
        now: float,
    ) -> CrossPlatformIdentityLink: ...

    async def for_onebot(
        self,
        onebot_qq_id: str,
    ) -> tuple[CrossPlatformIdentityLink, ...]: ...

    async def for_official(
        self,
        official: OfficialIdentity,
    ) -> CrossPlatformIdentityLink | None: ...

    async def all_links(self) -> tuple[CrossPlatformIdentityLink, ...]: ...

    async def revoke_onebot(self, onebot_qq_id: str, *, now: float) -> int: ...

    async def revoke_official(
        self,
        official: OfficialIdentity,
        *,
        now: float,
    ) -> bool: ...
