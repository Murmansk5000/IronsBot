# SPDX-License-Identifier: MIT
"""Explicit, token-confirmed identity links between supported QQ transports."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    IdentityLinkChallengeExpiredError,
    IdentityLinkChallengeInvalidError,
    IdentityLinkConflictError,
    IdentityLinkStore,
    OfficialIdentity,
    canonical_official_identity,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_TOKEN_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_TOKEN_LENGTH = 8


class IdentityLinkingError(ValueError):
    """A user-correctable identity linking failure."""

    @classmethod
    def invalid_ttl(cls) -> IdentityLinkingError:
        return cls("identity link challenge TTL must be positive")

    @classmethod
    def invalid_account_alias(cls) -> IdentityLinkingError:
        return cls("identity link account aliases must be canonical")

    @classmethod
    def duplicate_account_alias(cls) -> IdentityLinkingError:
        return cls("identity link account aliases must be unique after normalization")

    @classmethod
    def invalid_account_app_id(cls) -> IdentityLinkingError:
        return cls("identity link account AppIDs must be unique")


class IdentityLinkingPlatformError(IdentityLinkingError):
    @classmethod
    def onebot_required(cls) -> IdentityLinkingPlatformError:
        return cls("只能从数字账号接入端生成关联令牌。")

    @classmethod
    def official_required(cls) -> IdentityLinkingPlatformError:
        return cls("只能由官方机器人身份确认关联令牌。")


class IdentityLinkingAccountError(IdentityLinkingError):
    @classmethod
    def unknown(cls, reference: str, choices: str) -> IdentityLinkingAccountError:
        return cls(f"未知官方机器人账号“{reference}”，可选：{choices}。")

    @classmethod
    def unavailable(cls) -> IdentityLinkingAccountError:
        return cls("当前没有启用官方机器人账号。")

    @classmethod
    def selection_required(cls, choices: str) -> IdentityLinkingAccountError:
        return cls(f"请指定官方机器人账号：关联官方账号 {choices}。")


class IdentityLinkingTokenError(IdentityLinkingError):
    @classmethod
    def malformed(cls) -> IdentityLinkingTokenError:
        return cls("关联令牌格式不正确。")

    @classmethod
    def expired(cls) -> IdentityLinkingTokenError:
        return cls("关联令牌已过期，请在另一接入端重新生成。")

    @classmethod
    def invalid(cls) -> IdentityLinkingTokenError:
        return cls("关联令牌无效、已使用，或不属于当前官方机器人。")


class IdentityLinkingConflictError(IdentityLinkingError):
    @classmethod
    def already_linked(cls) -> IdentityLinkingConflictError:
        return cls("当前官方身份已经关联到另一个数字账号，请先解除原关联。")


@dataclass(frozen=True, slots=True)
class OfficialAccount:
    alias: str
    app_id: str


@dataclass(frozen=True, slots=True)
class IdentityLinkChallenge:
    account: OfficialAccount
    token: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class IdentityLinkingService:
    store: IdentityLinkStore
    accounts: Mapping[str, OfficialAccount]
    challenge_ttl_seconds: float = 600.0
    clock: Callable[[], float] = time.time
    on_link: Callable[[CrossPlatformIdentityLink], None] | None = None
    on_unlink: Callable[[CrossPlatformIdentityLink], None] | None = None

    def __post_init__(self) -> None:
        if self.challenge_ttl_seconds <= 0:
            raise IdentityLinkingError.invalid_ttl()
        normalized: dict[str, OfficialAccount] = {}
        app_ids: set[str] = set()
        for raw_alias, account in self.accounts.items():
            alias = raw_alias.strip().casefold()
            if not alias or alias != account.alias.strip().casefold():
                raise IdentityLinkingError.invalid_account_alias()
            if alias in normalized:
                raise IdentityLinkingError.duplicate_account_alias()
            app_id = account.app_id.strip()
            if not app_id or app_id in app_ids:
                raise IdentityLinkingError.invalid_account_app_id()
            normalized[alias] = OfficialAccount(alias, app_id)
            app_ids.add(app_id)
        object.__setattr__(self, "accounts", normalized)

    async def begin(
        self,
        actor: ActorRef,
        account_reference: str = "",
    ) -> IdentityLinkChallenge:
        onebot_qq_id = _onebot_qq_id(actor)
        account = self._resolve_account(account_reference)
        token = _new_token()
        now = self.clock()
        expires_at = now + self.challenge_ttl_seconds
        await self.store.issue(
            token_hash=_token_hash(token),
            onebot_qq_id=onebot_qq_id,
            official_app_id=account.app_id,
            created_at=now,
            expires_at=expires_at,
        )
        return IdentityLinkChallenge(account, token, expires_at)

    async def confirm(
        self,
        actor: ActorRef,
        token: str,
    ) -> CrossPlatformIdentityLink:
        official = _official_identity(actor)
        normalized = _normalize_token(token)
        if len(normalized) != _TOKEN_LENGTH:
            raise IdentityLinkingTokenError.malformed()
        try:
            link = await self.store.consume(
                token_hash=_token_hash(normalized),
                official=official,
                now=self.clock(),
            )
        except IdentityLinkChallengeExpiredError as exc:
            raise IdentityLinkingTokenError.expired() from exc
        except IdentityLinkChallengeInvalidError as exc:
            raise IdentityLinkingTokenError.invalid() from exc
        except IdentityLinkConflictError as exc:
            raise IdentityLinkingConflictError.already_linked() from exc
        if self.on_link is not None:
            self.on_link(link)
        return link

    async def links_for(self, actor: ActorRef) -> tuple[CrossPlatformIdentityLink, ...]:
        if actor.platform is Platform.ONEBOT:
            return await self.store.for_onebot(_onebot_qq_id(actor))
        official = _official_identity(actor)
        link = await self.store.for_official(official)
        return () if link is None else (link,)

    async def linked_onebot_actor(self, actor: ActorRef) -> ActorRef | None:
        """Resolve an exact, explicitly linked identity to its numeric QQ actor."""

        if actor.platform is Platform.ONEBOT:
            _onebot_qq_id(actor)
            return actor
        link = await self.store.for_official(_official_identity(actor))
        if link is None:
            return None
        return ActorRef(Platform.ONEBOT, link.onebot_qq_id)

    async def revoke(self, actor: ActorRef) -> int:
        now = self.clock()
        if actor.platform is Platform.ONEBOT:
            qq_id = _onebot_qq_id(actor)
            links = await self.store.for_onebot(qq_id)
            count = await self.store.revoke_onebot(qq_id, now=now)
        else:
            official = _official_identity(actor)
            link = await self.store.for_official(official)
            links = () if link is None else (link,)
            count = int(await self.store.revoke_official(official, now=now))
        if self.on_unlink is not None:
            for link in links:
                self.on_unlink(link)
        return count

    def _resolve_account(self, reference: str) -> OfficialAccount:
        normalized = reference.strip().casefold()
        if normalized:
            account = self.accounts.get(normalized)
            if account is None:
                choices = "、".join(sorted(self.accounts)) or "无"
                raise IdentityLinkingAccountError.unknown(
                    reference.strip(),
                    choices,
                )
            return account
        if len(self.accounts) == 1:
            return next(iter(self.accounts.values()))
        if not self.accounts:
            raise IdentityLinkingAccountError.unavailable()
        choices = "、".join(sorted(self.accounts))
        raise IdentityLinkingAccountError.selection_required(choices)


def _onebot_qq_id(actor: ActorRef) -> str:
    if actor.platform is not Platform.ONEBOT or not actor.id.isdecimal():
        raise IdentityLinkingPlatformError.onebot_required()
    return actor.id


def _official_identity(actor: ActorRef) -> OfficialIdentity:
    if actor.platform is not Platform.QQ_OFFICIAL or actor.account_id is None:
        raise IdentityLinkingPlatformError.official_required()
    return canonical_official_identity(
        OfficialIdentity(
            app_id=actor.account_id,
            kind=actor.kind,
            openid=actor.id,
            scope_id=actor.scope_id or "",
        )
    )


def _new_token() -> str:
    compact = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))
    return f"{compact[:4]}-{compact[4:]}"


def _normalize_token(token: str) -> str:
    return "".join(character for character in token.upper() if character.isalnum())


def _token_hash(token: str) -> str:
    return hashlib.sha256(_normalize_token(token).encode("ascii")).hexdigest()
