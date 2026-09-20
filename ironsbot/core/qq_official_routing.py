# SPDX-License-Identifier: MIT
"""Deterministic ownership for inbound QQ Official conversations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QQOfficialIngressRouting:
    """Choose one configured official account for each inbound conversation."""

    default_account_id: str
    preferred_accounts_by_onebot_group: dict[str, str]
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
        if conversation_kind != "group":
            return account_id == self.default_account_id
        onebot_group_id = self._onebot_groups_by_endpoint.get(
            (account_id, conversation_id)
        )
        if onebot_group_id is None:
            return explicitly_addressed or account_id == self.default_account_id
        preferred = self.preferred_accounts_by_onebot_group.get(onebot_group_id)
        return account_id == (preferred or self.default_account_id)
