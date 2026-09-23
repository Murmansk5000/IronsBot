# SPDX-License-Identifier: MIT
"""Platform-neutral feature-policy facts and decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.features import Feature
from ironsbot.core.platform import (
    ActorPrincipal,
    ActorRef,
    ConversationPrincipal,
    ConversationRef,
    Platform,
    is_supported_message_actor,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class IdentityPrincipalResolver(Protocol):
    def actor_principal(self, actor: ActorRef) -> ActorPrincipal: ...

    def conversation_principal(
        self,
        conversation: ConversationRef,
    ) -> ConversationPrincipal: ...

    def conversation_endpoints(
        self,
        principal: ConversationPrincipal,
    ) -> tuple[ConversationRef, ...]: ...


@dataclass(frozen=True, slots=True)
class FeatureService:
    """Answer feature-policy questions from already-resolved identities.

    Configuration adapters are responsible for expanding feature bundles and
    translating deployment-specific user or conversation references before
    constructing this service. The core never interprets native platform IDs.
    """

    group_features: Mapping[ConversationRef, frozenset[str]]
    actor_features: Mapping[ActorRef, frozenset[str]]
    superusers: frozenset[ActorRef]
    superuser_bypass: bool = True
    platform_default_features: Mapping[Platform, frozenset[str]] = field(
        default_factory=dict
    )
    account_default_features: Mapping[tuple[Platform, str], frozenset[str]] = field(
        default_factory=dict
    )
    principals: IdentityPrincipalResolver | None = field(
        default=None, compare=False, repr=False
    )

    @property
    def configured_feature_keys(self) -> frozenset[str]:
        """Return the atomic feature keys explicitly enabled by configuration.

        This is a configuration fact, not an authorization result: superuser
        bypass remains intentionally absent so compact plugin profiles validate
        only the features their policies actually request.
        """

        return frozenset(
            feature
            for features in (
                *self.group_features.values(),
                *self.actor_features.values(),
            )
            for feature in features
        )

    def is_actor_superuser(self, actor: ActorRef) -> bool:
        if self.actor_has_feature(actor, Feature.BLACKLIST.value):
            return False
        return any(
            self._same_actor_principal(actor, configured)
            for configured in self.superusers
        )

    def actor_has_feature(self, actor: ActorRef, feature: str) -> bool:
        return any(
            feature in features and self._same_actor_principal(actor, configured)
            for configured, features in self.actor_features.items()
        )

    def is_actor_feature_allowed(self, actor: ActorRef, feature: str) -> bool:
        if self.actor_has_feature(actor, Feature.BLACKLIST.value):
            return False
        return self.actor_has_feature(actor, feature) or (
            self.superuser_bypass and self.is_actor_superuser(actor)
        )

    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        return any(
            feature in features
            and self._same_conversation_principal(conversation, configured)
            for configured, features in self.group_features.items()
        )

    def is_feature_allowed(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        if not is_supported_message_actor(actor, conversation):
            return False
        if self.is_message_blocked(actor, conversation):
            return False
        if conversation.kind == "group":
            return self.conversation_has_feature(conversation, feature) or (
                self.superuser_bypass and self.is_actor_superuser(actor)
            )
        if conversation.kind == "private":
            return self.is_actor_feature_allowed(actor, feature)
        return False

    def is_message_blocked(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> bool:
        """Whether an incoming message must be ignored by feature policy."""

        if actor.platform is not conversation.platform:
            return False
        return self.actor_has_feature(actor, Feature.BLACKLIST.value) or (
            conversation.kind == "group"
            and self.conversation_has_feature(conversation, Feature.BLACKLIST.value)
        )

    def conversations_for_feature(self, feature: str) -> list[ConversationRef]:
        configured = [
            conversation
            for conversation, features in self.group_features.items()
            if feature in features
        ]
        if self.principals is None:
            return configured
        conversations: list[ConversationRef] = []
        for conversation in configured:
            principal = self.principals.conversation_principal(conversation)
            for endpoint in self.principals.conversation_endpoints(principal):
                if endpoint not in conversations:
                    conversations.append(endpoint)
        return conversations

    def actors_for_feature(self, feature: str) -> list[ActorRef]:
        return [
            actor
            for actor, features in self.actor_features.items()
            if feature in features
        ]

    def private_actors_for_feature(self, feature: str) -> list[ActorRef]:
        """Return feature actors that are valid direct-message destinations."""

        return [
            actor for actor in self.actors_for_feature(feature) if actor.kind == "user"
        ]

    def superuser_actors(self) -> list[ActorRef]:
        return sorted(
            self.superusers,
            key=lambda item: (
                item.platform.value,
                item.kind,
                item.scope_id or "",
                item.id,
            ),
        )

    def private_superuser_actors(self) -> list[ActorRef]:
        """Return only superusers whose identity is valid for direct messages."""

        return [actor for actor in self.superuser_actors() if actor.kind == "user"]

    def private_admin_notice_actors(self) -> list[ActorRef]:
        """Notification opt-in is independent of operator privileges."""
        return self.private_actors_for_feature(Feature.ADMIN_NOTICE.value)

    def _same_actor_principal(self, first: ActorRef, second: ActorRef) -> bool:
        if self.principals is None:
            return first == second
        first_principal = self.principals.actor_principal(first)
        return first_principal == self.principals.actor_principal(second)

    def _same_conversation_principal(
        self,
        first: ConversationRef,
        second: ConversationRef,
    ) -> bool:
        if self.principals is None:
            return first == second
        return self.principals.conversation_principal(
            first
        ) == self.principals.conversation_principal(second)
