# SPDX-License-Identifier: MIT
"""Resolve transport endpoints to non-addressable business principals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.platform import (
    ActorPrincipal,
    ActorRef,
    ConversationPrincipal,
    ConversationPrincipalKind,
    ConversationRef,
    OfficialUnionIdentity,
    Platform,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.identity_link_store import (
        CrossPlatformGroupLink,
        CrossPlatformIdentityLink,
        OfficialIdentity,
    )


@dataclass(frozen=True, slots=True)
class ActorPrincipalMerge:
    source: ActorPrincipal
    target: ActorPrincipal


@dataclass(frozen=True, slots=True)
class ConversationPrincipalMerge:
    source: ConversationPrincipal
    target: ConversationPrincipal


@dataclass(slots=True)
class IdentityPrincipalService:
    """Own endpoint-to-principal equivalence without changing send addresses."""

    _actor_principals: dict[ActorRef, ActorPrincipal] = field(default_factory=dict)
    _official_principals: dict[tuple[str, str], ActorPrincipal] = field(
        default_factory=dict
    )
    _union_principals: dict[tuple[str, str], ActorPrincipal] = field(
        default_factory=dict
    )
    _conversation_principals: dict[ConversationRef, ConversationPrincipal] = field(
        default_factory=dict
    )

    def actor_principal(self, actor: ActorRef) -> ActorPrincipal:
        if actor.platform is Platform.ONEBOT:
            return ActorPrincipal("qq", actor.id)
        existing = self._actor_principals.get(actor)
        if existing is None and actor.account_id is not None:
            existing = self._official_principals.get((actor.account_id, actor.id))
        if existing is not None:
            self._actor_principals[actor] = existing
            return existing
        principal = ActorPrincipal("official_endpoint", _actor_endpoint_id(actor))
        self._actor_principals[actor] = principal
        return principal

    def conversation_principal(
        self,
        conversation: ConversationRef,
    ) -> ConversationPrincipal:
        if conversation.platform is Platform.ONEBOT and conversation.kind == "group":
            return ConversationPrincipal("qq_group", conversation.id)
        existing = self._conversation_principals.get(conversation)
        if existing is not None:
            return existing
        kind: ConversationPrincipalKind = (
            "official_group"
            if conversation.platform is Platform.QQ_OFFICIAL
            and conversation.kind == "group"
            else "conversation"
        )
        principal = ConversationPrincipal(kind, _conversation_endpoint_id(conversation))
        self._conversation_principals[conversation] = principal
        return principal

    def observe_union_identity(
        self,
        *,
        actor: ActorRef,
        evidence: OfficialUnionIdentity,
    ) -> tuple[ActorPrincipalMerge, ...]:
        if actor.platform is not Platform.QQ_OFFICIAL:
            return ()
        identifiers = _union_identifiers(evidence)
        candidates = {
            principal
            for identifier in identifiers
            if (principal := self._union_principals.get(identifier)) is not None
        }
        endpoint_principal = self._actor_principals.get(actor)
        if endpoint_principal is not None:
            candidates.add(endpoint_principal)
        target = _select_actor_principal(candidates, identifiers)
        merges = self._replace_actor_principals(candidates, target)
        self._actor_principals[actor] = target
        if actor.account_id is not None:
            self._official_principals[(actor.account_id, actor.id)] = target
        for identifier in identifiers:
            self._union_principals[identifier] = target
        return merges

    def register_identity_link(
        self,
        link: CrossPlatformIdentityLink,
    ) -> tuple[ActorPrincipalMerge, ...]:
        return self.register_official_link(
            onebot_qq_id=link.onebot_qq_id,
            official=link.official,
        )

    def register_official_link(
        self,
        *,
        onebot_qq_id: str,
        official: OfficialIdentity,
    ) -> tuple[ActorPrincipalMerge, ...]:
        endpoint = (official.app_id, official.openid)
        current = self._official_principals.get(endpoint)
        target = ActorPrincipal("qq", onebot_qq_id)
        merges = self._replace_actor_principals(
            set() if current is None else {current},
            target,
        )
        self._official_principals[endpoint] = target
        for actor in tuple(self._actor_principals):
            if actor.account_id == official.app_id and actor.id == official.openid:
                self._actor_principals[actor] = target
        return merges

    def register_group_link(
        self,
        link: CrossPlatformGroupLink,
    ) -> tuple[ConversationPrincipalMerge, ...]:
        official = ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            link.official_group_openid,
            account_id=link.official_app_id,
        )
        current = self.conversation_principal(official)
        target = ConversationPrincipal("qq_group", link.onebot_group_id)
        self._conversation_principals[official] = target
        if current == target:
            return ()
        return (ConversationPrincipalMerge(current, target),)

    def _replace_actor_principals(
        self,
        sources: Iterable[ActorPrincipal],
        target: ActorPrincipal,
    ) -> tuple[ActorPrincipalMerge, ...]:
        replaced = {source for source in sources if source != target}
        if not replaced:
            return ()
        for actor, principal in tuple(self._actor_principals.items()):
            if principal in replaced:
                self._actor_principals[actor] = target
        for identifier, principal in tuple(self._union_principals.items()):
            if principal in replaced:
                self._union_principals[identifier] = target
        for endpoint, principal in tuple(self._official_principals.items()):
            if principal in replaced:
                self._official_principals[endpoint] = target
        return tuple(
            ActorPrincipalMerge(source, target)
            for source in sorted(replaced, key=lambda item: (item.kind, item.id))
        )


def _select_actor_principal(
    candidates: set[ActorPrincipal],
    identifiers: tuple[tuple[str, str], ...],
) -> ActorPrincipal:
    qq_principals = sorted(
        (principal for principal in candidates if principal.kind == "qq"),
        key=lambda item: item.id,
    )
    if qq_principals:
        return qq_principals[0]
    union_principals = sorted(
        (principal for principal in candidates if principal.kind == "official_union"),
        key=lambda item: item.id,
    )
    if union_principals:
        return union_principals[0]
    return ActorPrincipal("official_union", _union_principal_id(identifiers))


def _union_identifiers(
    evidence: OfficialUnionIdentity,
) -> tuple[tuple[str, str], ...]:
    identifiers: list[tuple[str, str]] = []
    if evidence.union_openid is not None:
        identifiers.append(("union_openid", evidence.union_openid))
    if evidence.union_user_account is not None:
        identifiers.append(("union_user_account", evidence.union_user_account))
    return tuple(identifiers)


def _union_principal_id(identifiers: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(identifiers, ensure_ascii=True, separators=(",", ":"))


def _actor_endpoint_id(actor: ActorRef) -> str:
    return json.dumps(
        (
            actor.platform.value,
            actor.account_id or "",
            actor.kind,
            actor.id,
            actor.scope_id or "",
        ),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _conversation_endpoint_id(conversation: ConversationRef) -> str:
    return json.dumps(
        (
            conversation.platform.value,
            conversation.account_id or "",
            conversation.kind,
            conversation.id,
        ),
        ensure_ascii=True,
        separators=(",", ":"),
    )
