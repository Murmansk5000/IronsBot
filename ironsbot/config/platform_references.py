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
    from collections.abc import Iterable, Mapping

    from ironsbot.config.onebot_references import OneBotReferenceResolver


class PlatformReferenceError(ValueError):
    @classmethod
    def no_private_endpoint(
        cls,
        location: str,
        alias: str,
    ) -> PlatformReferenceError:
        return cls(
            f"{location} user alias has only group-scoped member endpoints: {alias}"
        )


class QQOfficialReferenceAccount(Protocol):
    @property
    def app_id(self) -> str: ...

    @property
    def group_aliases(self) -> Mapping[str, str]: ...

    @property
    def user_aliases(self) -> Mapping[str, str]: ...

    @property
    def group_member_aliases(self) -> Mapping[str, Mapping[str, str]]: ...


@dataclass(frozen=True, slots=True)
class PlatformReferenceResolver:
    """Resolve logical aliases into platform-scoped delivery endpoints."""

    onebot: OneBotReferenceResolver
    qq_groups: Mapping[str, tuple[ConversationRef, ...]]
    qq_users: Mapping[str, tuple[ActorRef, ...]]
    qq_members: Mapping[str, tuple[ActorRef, ...]]

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
        actors.extend(self.qq_members.get(value, ()))
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
        if value in self.qq_members:
            raise PlatformReferenceError.no_private_endpoint(location, value)
        return tuple(
            self.onebot.private_conversation_refs([reference], location=location)
        )


def build_platform_reference_resolver(
    onebot: OneBotReferenceResolver,
    qq_accounts: Iterable[QQOfficialReferenceAccount],
) -> PlatformReferenceResolver:
    """Build logical group aliases and strict user aliases across platforms."""

    qq_groups: dict[str, list[ConversationRef]] = {}
    qq_users: dict[str, list[ActorRef]] = {}
    qq_members: dict[str, list[ActorRef]] = {}
    for account in qq_accounts:
        for alias, openid in account.group_aliases.items():
            qq_groups.setdefault(alias, []).append(
                ConversationRef(
                    Platform.QQ_OFFICIAL,
                    "group",
                    openid,
                    account_id=account.app_id,
                )
            )
        for alias, openid in account.user_aliases.items():
            qq_users.setdefault(alias, []).append(
                ActorRef(
                    Platform.QQ_OFFICIAL,
                    openid,
                    account_id=account.app_id,
                )
            )
        for group_reference, aliases in account.group_member_aliases.items():
            group_openid = account.group_aliases.get(group_reference, group_reference)
            for alias, member_openid in aliases.items():
                qq_members.setdefault(alias, []).append(
                    ActorRef(
                        Platform.QQ_OFFICIAL,
                        member_openid,
                        "member",
                        group_openid,
                        account.app_id,
                    )
                )
    return PlatformReferenceResolver(
        onebot,
        {alias: tuple(conversations) for alias, conversations in qq_groups.items()},
        {alias: tuple(actors) for alias, actors in qq_users.items()},
        {alias: tuple(actors) for alias, actors in qq_members.items()},
    )
