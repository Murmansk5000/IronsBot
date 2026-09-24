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


class IdentityPrincipalConflictError(ValueError):
    def __init__(self) -> None:
        super().__init__("official identity component has conflicting principals")


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
    _union_identifiers_by_endpoint: dict[tuple[str, str], set[tuple[str, str]]] = field(
        default_factory=dict
    )
    _explicit_qq_links: dict[tuple[str, str], str] = field(default_factory=dict)
    _member_endpoints_by_qq_app: dict[tuple[str, str], set[str]] = field(
        default_factory=dict
    )
    _configured_actor_principals: dict[tuple[str, str], ActorPrincipal] = field(
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
        principal = default_actor_principal(actor)
        self._actor_principals[actor] = principal
        if actor.account_id is not None:
            self._official_principals[(actor.account_id, actor.id)] = principal
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
        principal = default_conversation_principal(conversation)
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
        endpoint = _official_endpoint(actor)
        self._union_identifiers_by_endpoint.setdefault(endpoint, set()).update(
            identifiers
        )
        candidates = {
            principal
            for identifier in identifiers
            if (principal := self._union_principals.get(identifier)) is not None
        }
        candidates.add(self.actor_principal(actor))
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
        self._explicit_qq_links[endpoint] = onebot_qq_id
        if official.kind == "member":
            self._member_endpoints_by_qq_app.setdefault(
                (onebot_qq_id, official.app_id), set()
            ).add(official.openid)
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

    def register_configured_actor(
        self,
        *,
        alias: str,
        onebot_qq_id: str | None,
        official_endpoints: Iterable[tuple[str, str]],
    ) -> None:
        target = (
            ActorPrincipal("qq", onebot_qq_id)
            if onebot_qq_id is not None
            else ActorPrincipal("configured_user", alias)
        )
        for endpoint in official_endpoints:
            self._configured_actor_principals[endpoint] = target
            self._official_principals[endpoint] = target

    def unregister_identity_link(
        self,
        link: CrossPlatformIdentityLink,
    ) -> None:
        endpoint = (link.official.app_id, link.official.openid)
        if self._explicit_qq_links.get(endpoint) != link.onebot_qq_id:
            return
        self._explicit_qq_links.pop(endpoint)
        if link.official.kind == "member":
            members = self._member_endpoints_by_qq_app.get(
                (link.onebot_qq_id, link.official.app_id)
            )
            if members is not None:
                members.discard(link.official.openid)
        component = self._official_component(endpoint)
        target = self._component_target(component)
        for member in component:
            self._official_principals[member] = target
        for actor in tuple(self._actor_principals):
            if _official_endpoint(actor) in component:
                self._actor_principals[actor] = target
        for member in component:
            for identifier in self._union_identifiers_by_endpoint.get(member, set()):
                self._union_principals[identifier] = target

    def register_configured_group(
        self,
        *,
        alias: str,
        onebot_group_id: str | None,
        official_endpoints: Iterable[tuple[str, str]],
    ) -> tuple[ConversationPrincipalMerge, ...]:
        target = (
            ConversationPrincipal("qq_group", onebot_group_id)
            if onebot_group_id is not None
            else ConversationPrincipal("configured_group", alias)
        )
        sources: set[ConversationPrincipal] = set()
        for app_id, group_openid in official_endpoints:
            conversation = ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                group_openid,
                account_id=app_id,
            )
            sources.add(self.conversation_principal(conversation))
            self._conversation_principals[conversation] = target
        return tuple(
            ConversationPrincipalMerge(source, target)
            for source in sorted(
                sources - {target},
                key=lambda item: (item.kind, item.id),
            )
        )

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

    def onebot_actor(self, actor: ActorRef) -> ActorRef | None:
        principal = self.actor_principal(actor)
        if principal.kind != "qq":
            return None
        return ActorRef(Platform.ONEBOT, principal.id)

    def official_group_member_for_qq(
        self,
        qq_id: str,
        conversation: ConversationRef,
    ) -> ActorRef | None:
        if (
            conversation.platform is not Platform.QQ_OFFICIAL
            or conversation.kind != "group"
        ):
            return None
        members = self._member_endpoints_by_qq_app.get(
            (qq_id, conversation.account_id or ""), set()
        )
        if len(members) != 1:
            return None
        return ActorRef(
            Platform.QQ_OFFICIAL,
            next(iter(members)),
            "member",
            conversation.id,
            account_id=conversation.account_id,
        )

    def register_private_link(
        self,
        link: CrossPlatformIdentityLink,
    ) -> tuple[ConversationPrincipalMerge, ...]:
        # TODO(identity-migration): member_openid is temporarily accepted as a
        # C2C address for the same AppID. Restore a user-only check after the
        # production address database has verified both source types.
        if link.official.kind not in {"member", "user"}:
            return ()
        endpoint = ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            link.official.openid,
            account_id=link.official.app_id,
        )
        source = self.conversation_principal(endpoint)
        target = self.conversation_principal(
            ConversationRef(Platform.ONEBOT, "private", link.onebot_qq_id)
        )
        self._conversation_principals[endpoint] = target
        return () if source == target else (ConversationPrincipalMerge(source, target),)

    def unregister_private_link(self, link: CrossPlatformIdentityLink) -> None:
        if link.official.kind in {"member", "user"}:
            self._conversation_principals.pop(
                ConversationRef(
                    Platform.QQ_OFFICIAL,
                    "private",
                    link.official.openid,
                    account_id=link.official.app_id,
                ),
                None,
            )

    def conversation_endpoints(
        self,
        principal: ConversationPrincipal,
    ) -> tuple[ConversationRef, ...]:
        endpoints = [
            conversation
            for conversation, resolved in self._conversation_principals.items()
            if resolved == principal
        ]
        if principal.kind == "qq_group":
            onebot = ConversationRef(Platform.ONEBOT, "group", principal.id)
            if onebot not in endpoints:
                endpoints.insert(0, onebot)
        return tuple(endpoints)

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

    def _official_component(
        self,
        endpoint: tuple[str, str],
    ) -> set[tuple[str, str]]:
        component = {endpoint}
        identifiers = set(self._union_identifiers_by_endpoint.get(endpoint, set()))
        changed = True
        while changed:
            changed = False
            for (
                candidate,
                candidate_identifiers,
            ) in self._union_identifiers_by_endpoint.items():
                if candidate in component or not identifiers.intersection(
                    candidate_identifiers
                ):
                    continue
                component.add(candidate)
                identifiers.update(candidate_identifiers)
                changed = True
        return component

    def _component_target(
        self,
        component: set[tuple[str, str]],
    ) -> ActorPrincipal:
        configured = {
            principal
            for endpoint in component
            if (principal := self._configured_actor_principals.get(endpoint))
            is not None
        }
        explicit = {
            ActorPrincipal("qq", qq_id)
            for endpoint in component
            if (qq_id := self._explicit_qq_links.get(endpoint)) is not None
        }
        authoritative = configured | explicit
        if len(authoritative) > 1:
            raise IdentityPrincipalConflictError
        if authoritative:
            return next(iter(authoritative))
        identifiers = tuple(
            sorted(
                {
                    identifier
                    for endpoint in component
                    for identifier in self._union_identifiers_by_endpoint.get(
                        endpoint, set()
                    )
                }
            )
        )
        if identifiers:
            return ActorPrincipal("official_union", _union_principal_id(identifiers))
        endpoint = next(iter(component))
        return ActorPrincipal("official_endpoint", _official_endpoint_id(endpoint))


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


def _official_endpoint(actor: ActorRef) -> tuple[str, str]:
    return (actor.account_id or "", actor.id)


def _official_endpoint_id(endpoint: tuple[str, str]) -> str:
    return json.dumps(endpoint, ensure_ascii=True, separators=(",", ":"))


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


def default_actor_principal(actor: ActorRef) -> ActorPrincipal:
    """Return the standalone principal before trusted links are observed."""

    if actor.platform is Platform.ONEBOT:
        return ActorPrincipal("qq", actor.id)
    return ActorPrincipal("official_endpoint", _actor_endpoint_id(actor))


def default_conversation_principal(
    conversation: ConversationRef,
) -> ConversationPrincipal:
    """Return the standalone conversation owner before trusted links are observed."""

    if conversation.platform is Platform.ONEBOT and conversation.kind == "group":
        return ConversationPrincipal("qq_group", conversation.id)
    kind: ConversationPrincipalKind = (
        "official_group"
        if conversation.platform is Platform.QQ_OFFICIAL
        and conversation.kind == "group"
        else "conversation"
    )
    return ConversationPrincipal(kind, _conversation_endpoint_id(conversation))
