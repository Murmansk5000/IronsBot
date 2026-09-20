# SPDX-License-Identifier: MIT
"""Resolve configured aliases into platform-scoped identity values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    Platform,
    private_conversation_for_actor,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.identities import IdentityConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver


class PlatformReferenceError(ValueError):
    @classmethod
    def missing_official_endpoint(
        cls,
        location: str,
        alias: str,
        account_alias: str,
    ) -> PlatformReferenceError:
        return cls(
            f"{location} identity {alias} has no official endpoint for "
            f"account {account_alias}"
        )


class QQOfficialReferenceAccount(Protocol):
    @property
    def app_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PlatformReferenceResolver:
    """Resolve logical aliases into platform-scoped delivery endpoints."""

    onebot: OneBotReferenceResolver
    qq_groups: Mapping[str, tuple[ConversationRef, ...]]
    qq_users: Mapping[str, tuple[ActorRef, ...]]
    account_app_ids: Mapping[str, str]

    def group_conversation_refs(
        self,
        reference: object,
        *,
        location: str,
    ) -> tuple[ConversationRef, ...]:
        value = str(reference).strip()
        conversations: list[ConversationRef] = []
        if value in self.onebot.group_aliases:
            conversations.append(
                self.onebot.group_conversation_ref(reference, location=location)
            )
        conversations.extend(self.qq_groups.get(value, ()))
        if conversations:
            return tuple(conversations)
        return (self.onebot.group_conversation_ref(reference, location=location),)

    def actor_refs(
        self,
        reference: object,
        *,
        location: str,
    ) -> tuple[ActorRef, ...]:
        value = str(reference).strip()
        actors: list[ActorRef] = []
        if value in self.onebot.user_aliases:
            actors.append(self.onebot.actor_ref(reference, location=location))
        actors.extend(self.qq_users.get(value, ()))
        if actors:
            return tuple(actors)
        return (self.onebot.actor_ref(reference, location=location),)

    def private_conversation_refs(
        self,
        reference: object,
        *,
        location: str,
    ) -> tuple[ConversationRef, ...]:
        value = str(reference).strip()
        actors: list[ActorRef] = []
        if value in self.onebot.user_aliases:
            actors.append(self.onebot.actor_ref(reference, location=location))
        actors.extend(self.qq_users.get(value, ()))
        if actors:
            return tuple(private_conversation_for_actor(actor) for actor in actors)
        return tuple(
            self.onebot.private_conversation_refs([reference], location=location)
        )

    def official_group_conversation_ref(
        self,
        reference: object,
        *,
        account_alias: str,
        location: str,
    ) -> ConversationRef:
        alias = str(reference).strip()
        app_id = self.account_app_ids[account_alias]
        endpoint = next(
            (
                candidate
                for candidate in self.qq_groups.get(alias, ())
                if candidate.account_id == app_id
            ),
            None,
        )
        if endpoint is None:
            raise PlatformReferenceError.missing_official_endpoint(
                location,
                alias,
                account_alias,
            )
        return endpoint

    def official_actor_ref(
        self,
        reference: object,
        *,
        account_alias: str,
        location: str,
    ) -> ActorRef:
        alias = str(reference).strip()
        app_id = self.account_app_ids[account_alias]
        endpoint = next(
            (
                candidate
                for candidate in self.qq_users.get(alias, ())
                if candidate.account_id == app_id
            ),
            None,
        )
        if endpoint is None:
            raise PlatformReferenceError.missing_official_endpoint(
                location,
                alias,
                account_alias,
            )
        return endpoint


def build_platform_reference_resolver(
    onebot: OneBotReferenceResolver,
    identities: IdentityConfig,
    qq_accounts: Mapping[str, QQOfficialReferenceAccount],
) -> PlatformReferenceResolver:
    """Build logical group aliases and strict user aliases across platforms."""

    qq_groups: dict[str, list[ConversationRef]] = {}
    qq_users: dict[str, list[ActorRef]] = {}
    for alias, target in identities.groups.items():
        for account_alias, openid in target.official.items():
            account = qq_accounts.get(account_alias)
            if account is None:
                continue
            qq_groups.setdefault(alias, []).append(
                ConversationRef(
                    Platform.QQ_OFFICIAL,
                    "group",
                    openid,
                    account_id=account.app_id,
                )
            )
    for alias, target in identities.users.items():
        for account_alias, openid in target.official.items():
            account = qq_accounts.get(account_alias)
            if account is None:
                continue
            qq_users.setdefault(alias, []).append(
                ActorRef(
                    Platform.QQ_OFFICIAL,
                    openid,
                    account_id=account.app_id,
                )
            )
    return PlatformReferenceResolver(
        onebot,
        {alias: tuple(conversations) for alias, conversations in qq_groups.items()},
        {alias: tuple(actors) for alias, actors in qq_users.items()},
        {alias: account.app_id for alias, account in qq_accounts.items()},
    )
