# SPDX-License-Identifier: MIT
"""Resolve configured QQ recipients using verified C2C endpoints only."""

import logging
from dataclasses import dataclass, field

from ironsbot.core.platform import ConversationRef, Platform, reference_digest
from ironsbot.services.identity_link_store import CrossPlatformIdentityLink

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PrivateConversationRoutes:
    onebot_enabled: bool = True
    official_accounts: frozenset[str] = frozenset()
    default_account: str | None = None
    _links: dict[ConversationRef, str] = field(default_factory=dict)
    _warned: set[str] = field(default_factory=set)

    def register(self, link: CrossPlatformIdentityLink) -> None:
        # A member identity proves ownership, not a C2C sending address.
        if link.official.kind != "user":
            return
        self._links[self._endpoint(link)] = link.onebot_qq_id
        self._warned.discard(link.onebot_qq_id)

    def unregister(self, link: CrossPlatformIdentityLink) -> None:
        if link.official.kind == "user":
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
        if (
            source.kind != "private"
            or source.platform is not Platform.ONEBOT
            or self.onebot_enabled
        ):
            return source
        candidates = [
            endpoint
            for endpoint, qq_id in self._links.items()
            if qq_id == source.id and endpoint.account_id in self.official_accounts
        ]
        preferred = [c for c in candidates if c.account_id == self.default_account]
        if len(preferred) == 1:
            return preferred[0]
        if len(candidates) == 1:
            return candidates[0]
        if source.id not in self._warned:
            self._warned.add(source.id)
            _LOGGER.warning(
                "Private route unresolved: recipient=%s reason=%s; "
                "configure or verify a C2C user_openid for the intended bot; "
                "member_openid is not a private address",
                reference_digest(source.id),
                "ambiguous C2C endpoints" if candidates else "missing C2C endpoint",
            )
        return source
