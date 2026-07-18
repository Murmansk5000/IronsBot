from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.admin_priority import AdminPriorityService
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.team_resource_subscriptions import TeamResourceService
    from ironsbot.shared.features import FeatureService


@dataclass(frozen=True, slots=True)
class SeerQueryResources:
    config: SeerConfig
    headless: HeadlessService
    features: FeatureService
    priority: AdminPriorityService
    team_resource: TeamResourceService
