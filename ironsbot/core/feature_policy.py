# SPDX-License-Identifier: MIT
"""Platform-neutral feature-policy facts and decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    Platform,
    is_supported_message_actor,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    linked_onebot_ids: dict[tuple[str, str], str] = field(
        default_factory=dict,
        compare=False,
        repr=False,
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
                *self.platform_default_features.values(),
                *self.account_default_features.values(),
            )
            for feature in features
        )

    def is_actor_superuser(self, actor: ActorRef) -> bool:
        return actor in self.superusers or any(
            _same_official_principal(actor, configured)
            for configured in self.superusers
        ) or self._linked_onebot_actor(actor) in self.superusers

    def actor_has_feature(self, actor: ActorRef, feature: str) -> bool:
        if feature in self.actor_features.get(actor, frozenset()):
            return True
        linked = self._linked_onebot_actor(actor)
        if linked is not None and feature in self.actor_features.get(
            linked,
            frozenset(),
        ):
            return True
        return any(
            feature in features and _same_official_principal(actor, configured)
            for configured, features in self.actor_features.items()
        )

    def register_identity_link(
        self,
        *,
        official_app_id: str,
        official_openid: str,
        onebot_qq_id: str,
    ) -> None:
        self.linked_onebot_ids[(official_app_id, official_openid)] = onebot_qq_id

    def unregister_identity_link(
        self,
        *,
        official_app_id: str,
        official_openid: str,
    ) -> None:
        self.linked_onebot_ids.pop((official_app_id, official_openid), None)

    def _linked_onebot_actor(self, actor: ActorRef) -> ActorRef | None:
        if actor.platform is not Platform.QQ_OFFICIAL or actor.account_id is None:
            return None
        qq_id = self.linked_onebot_ids.get((actor.account_id, actor.id))
        return None if qq_id is None else ActorRef(Platform.ONEBOT, qq_id)

    def is_actor_feature_allowed(self, actor: ActorRef, feature: str) -> bool:
        return (
            self.actor_has_feature(actor, feature)
            or feature in self._default_features(actor.platform, actor.account_id)
            or (
                self.superuser_bypass and self.is_actor_superuser(actor)
            )
        )

    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        return feature in self.group_features.get(conversation, frozenset()) or (
            feature
            in self._default_features(
                conversation.platform,
                conversation.account_id,
            )
        )

    def _default_features(
        self,
        platform: Platform,
        account_id: str | None,
    ) -> frozenset[str]:
        if account_id is not None:
            account_features = self.account_default_features.get(
                (platform, account_id)
            )
            if account_features is not None:
                return account_features
        return self.platform_default_features.get(platform, frozenset())

    def is_feature_allowed(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        if not is_supported_message_actor(actor, conversation):
            return False
        if conversation.kind == "group":
            return (
                self.conversation_has_feature(conversation, feature)
                or self.actor_has_feature(actor, feature)
                or (self.superuser_bypass and self.is_actor_superuser(actor))
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
        return [
            conversation
            for conversation, features in self.group_features.items()
            if feature in features
        ]

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

    def private_actors_with_superusers(self, feature: str) -> list[ActorRef]:
        """Return private feature actors and private superusers once each."""

        actors = self.private_actors_for_feature(feature)
        actors.extend(
            actor for actor in self.private_superuser_actors() if actor not in actors
        )
        return actors


def _same_official_principal(first: ActorRef, second: ActorRef) -> bool:
    return (
        first.platform is Platform.QQ_OFFICIAL
        and second.platform is Platform.QQ_OFFICIAL
        and first.account_id == second.account_id
        and first.id == second.id
    )
