from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.admin_priority import AdminPriorityService
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.rank_display import RankDisplayService
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.team_resource_subscriptions import TeamResourceService
    from ironsbot.shared.features import FeatureService


@dataclass(frozen=True, slots=True)
class SeerQueryResources:
    config: SeerConfig
    rank_display: RankDisplayService
    rank_page_refresh: RankPageRefreshService
    render_cache: RenderCache
    headless: HeadlessService
    features: FeatureService
    priority: AdminPriorityService
    team_resource: TeamResourceService
