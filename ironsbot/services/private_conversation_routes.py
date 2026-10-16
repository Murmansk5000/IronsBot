# SPDX-License-Identifier: MIT
"""Resolve configured QQ recipients using known official user endpoints."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from ironsbot.core.platform import ConversationRef, Platform, reference_digest
from ironsbot.core.push_routing import PushRouteDecision
from ironsbot.services.identity_link_store import CrossPlatformIdentityLink

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PrivateConversationRoutes:
    onebot_enabled: bool = True
    official_accounts: frozenset[str] = frozenset()
    default_account: str | None = None
    preferred_accounts: dict[str, str] = field(default_factory=dict)
    use_default_for_unconfigured_targets: bool = False
    onebot_preferred_users: frozenset[str] = frozenset()
    group_route: Callable[[ConversationRef], PushRouteDecision] | None = None
    _links: dict[ConversationRef, str] = field(default_factory=dict)
    _warned: set[str] = field(default_factory=set)

    def register(self, link: CrossPlatformIdentityLink) -> None:
        # TODO(identity-migration): Treat member_openid and user_openid as the
        # same AppID-scoped address until production observations are migrated.
        if link.official.kind not in {"member", "user"}:
            return
        self._links[self._endpoint(link)] = link.onebot_qq_id
        self._warned.discard(link.onebot_qq_id)

    def unregister(self, link: CrossPlatformIdentityLink) -> None:
        if link.official.kind in {"member", "user"}:
            self._links.pop(self._endpoint(link), None)

    @staticmethod
    def _endpoint(link: CrossPlatformIdentityLink) -> ConversationRef:
        return ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            link.official.openid,
            account_id=link.official.app_id,
        )

    def resolve(self, source: ConversationRef) -> ConversationRef:
        return self.decision_for(source).target

    def decision_for(self, source: ConversationRef) -> PushRouteDecision:  # noqa: PLR0911
        if source.kind != "private":
            return (
                self.group_route(source)
                if self.group_route is not None
                else PushRouteDecision("ready", source)
            )
        if source.platform is Platform.QQ_OFFICIAL:
            qq_id = self._links.get(source)
            if qq_id is not None:
                return self.decision_for(
                    ConversationRef(Platform.ONEBOT, "private", qq_id)
                )
            # An explicit AppID-scoped C2C endpoint does not use default routing.
            return PushRouteDecision(
                "ready"
                if source.account_id in self.official_accounts
                else "unavailable",
                source,
                ""
                if source.account_id in self.official_accounts
                else "unknown_account",
            )
        if source.platform is not Platform.ONEBOT:
            return PushRouteDecision("unavailable", source, "unsupported_platform")
        explicit = (
            source.id in self.onebot_preferred_users
            if self.onebot_enabled
            else source.id in self.preferred_accounts
        )
        if not explicit and not self.use_default_for_unconfigured_targets:
            return PushRouteDecision("skipped", source, "unconfigured_target")
        if self.onebot_enabled:
            return PushRouteDecision("ready", source)
        candidates = [
            endpoint
            for endpoint, qq_id in self._links.items()
            if qq_id == source.id and endpoint.account_id in self.official_accounts
        ]
        account = self.preferred_accounts.get(source.id, self.default_account)
        preferred = [c for c in candidates if c.account_id == account]
        if len(preferred) == 1:
            return PushRouteDecision("ready", preferred[0])
        if source.id not in self._warned:
            self._warned.add(source.id)
            _LOGGER.warning(
                "Private route unresolved: recipient=%s reason=%s; "
                "configure or observe an AppID-scoped OpenID for the intended bot",
                reference_digest(source.id),
                (
                    "missing C2C endpoint for selected account"
                    if candidates
                    else "missing C2C endpoint"
                ),
            )
        return PushRouteDecision("unavailable", source, "private_route_unavailable")

    def selected_for(self, conversation: ConversationRef) -> ConversationRef | None:
        """Return the sole permitted private push endpoint for a known recipient."""
        decision = self.decision_for(conversation)
        return decision.target if decision.status == "ready" else None
