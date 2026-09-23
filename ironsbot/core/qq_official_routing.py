# SPDX-License-Identifier: MIT
"""Deterministic ownership for inbound QQ Official conversations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QQOfficialIngressRouting:
    """Choose one configured official account for each inbound conversation."""

    default_account_id: str
    preferred_accounts_by_onebot_group: dict[str, str]
    use_default_for_unconfigured_groups: bool = False
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
                self.use_default_for_unconfigured_groups
                and account_id == self.default_account_id
            )
        preferred = self.preferred_accounts_by_onebot_group.get(onebot_group_id)
        if preferred is not None:
            return account_id == preferred
        return (
            self.use_default_for_unconfigured_groups
            and account_id == self.default_account_id
        )
