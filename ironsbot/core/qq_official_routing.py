# SPDX-License-Identifier: MIT
"""Deterministic ownership for inbound QQ Official conversations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.push_routing import PushRouteDecision

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef


@dataclass(slots=True)
class QQOfficialIngressRouting:
    """Choose one configured official account for each inbound conversation."""

    default_account_id: str
    preferred_accounts_by_onebot_group: dict[str, str]
    use_default_for_unconfigured_targets: bool = False
    _onebot_groups_by_endpoint: dict[tuple[str, str], str] = field(
        default_factory=dict,
        repr=False,
    )

    def register_group_endpoint(
        self,
        *,
        account_id: str,
        official_group_openid: str,
        onebot_group_id: str,
    ) -> None:
        self._onebot_groups_by_endpoint[(account_id, official_group_openid)] = (
            onebot_group_id
        )

    def allows(
        self,
        *,
        account_id: str,
        conversation_kind: str,
        conversation_id: str,
        explicitly_addressed: bool = False,
    ) -> bool:
        del explicitly_addressed  # Addressing cannot bypass configured group ownership.
        if conversation_kind != "group":
            return True
        onebot_group_id = self._onebot_groups_by_endpoint.get(
            (account_id, conversation_id)
        )
        if onebot_group_id is None:
            return (
                self.use_default_for_unconfigured_targets
                and account_id == self.default_account_id
            )
        preferred = self.preferred_accounts_by_onebot_group.get(onebot_group_id)
        if preferred is not None:
            return account_id == preferred
        return (
            self.use_default_for_unconfigured_targets
            and account_id == self.default_account_id
        )

    def push_route(self, conversation: ConversationRef) -> PushRouteDecision:
        group = self._onebot_groups_by_endpoint.get(
            (conversation.account_id or "", conversation.id)
        )
        preferred = self.preferred_accounts_by_onebot_group.get(group or "")
        if preferred is None and not self.use_default_for_unconfigured_targets:
            return PushRouteDecision("skipped", conversation, "unconfigured_target")
        selected = preferred or self.default_account_id
        if selected != conversation.account_id:
            return PushRouteDecision("skipped", conversation, "different_group_owner")
        return PushRouteDecision("ready", conversation)
