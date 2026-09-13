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
    def duplicate_alias(cls, kind: str, alias: str) -> PlatformReferenceError:
        return cls(f"configured {kind} alias is not globally unique: {alias}")


class QQOfficialReferenceAccount(Protocol):
    @property
    def app_id(self) -> str: ...

    @property
    def group_aliases(self) -> Mapping[str, str]: ...

    @property
    def user_aliases(self) -> Mapping[str, str]: ...


@dataclass(frozen=True, slots=True)
class PlatformReferenceResolver:
    """Resolve one alias to exactly one platform account and target."""

    onebot: OneBotReferenceResolver
    qq_groups: Mapping[str, ConversationRef]
    qq_users: Mapping[str, ActorRef]

    def group_conversation_ref(
        self,
        reference: object,
        *,
        location: str,
    ) -> ConversationRef:
        value = str(reference).strip()
        if value in self.qq_groups:
            return self.qq_groups[value]
        return self.onebot.group_conversation_ref(reference, location=location)

    def private_conversation_ref(
        self,
        reference: object,
        *,
        location: str,
    ) -> ConversationRef:
        value = str(reference).strip()
        if value in self.qq_users:
            return private_conversation_for_actor(self.qq_users[value])
        return self.onebot.private_conversation_refs(
            [reference],
            location=location,
        )[0]


def build_platform_reference_resolver(
    onebot: OneBotReferenceResolver,
    qq_accounts: Iterable[QQOfficialReferenceAccount],
) -> PlatformReferenceResolver:
    """Build a strict alias registry across OneBot and official bot accounts."""

    occupied_groups = set(onebot.group_aliases)
    occupied_users = set(onebot.user_aliases)
    qq_groups: dict[str, ConversationRef] = {}
    qq_users: dict[str, ActorRef] = {}
    for account in qq_accounts:
        for alias, openid in account.group_aliases.items():
            if alias in occupied_groups:
                raise PlatformReferenceError.duplicate_alias("group", alias)
            occupied_groups.add(alias)
            qq_groups[alias] = ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                openid,
                account_id=account.app_id,
            )
        for alias, openid in account.user_aliases.items():
            if alias in occupied_users:
                raise PlatformReferenceError.duplicate_alias("user", alias)
            occupied_users.add(alias)
            qq_users[alias] = ActorRef(
                Platform.QQ_OFFICIAL,
                openid,
                account_id=account.app_id,
            )
    return PlatformReferenceResolver(onebot, qq_groups, qq_users)
