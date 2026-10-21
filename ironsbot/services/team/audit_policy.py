# SPDX-License-Identifier: MIT
"""Shared feature policy for team-audit conversations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.team.audit import TEAM_AUDIT_FEATURE

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ConversationRef


@dataclass(frozen=True, slots=True)
class FeatureTeamAuditPolicy:
    features: FeatureService

    def enabled_for(self, conversation: ConversationRef) -> bool:
        return self.features.conversation_has_feature(conversation, TEAM_AUDIT_FEATURE)
