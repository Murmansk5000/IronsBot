from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.services.seer.autocard import AutocardService
    from ironsbot.services.seer.autocard_sanctuary import AutocardSanctuaryService
    from ironsbot.services.seer.battle_effect import BattleEffectQueryService
    from ironsbot.services.seer.countermark_stat_rank import (
        CountermarkStatRankService,
    )
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.equipment import EquipmentQueryService
    from ironsbot.services.seer.external_references import SeerInfoReferences
    from ironsbot.services.seer.mintmark import MintmarkQueryService
    from ironsbot.services.seer.new_content import (
        NewContentCategory,
        NewContentSnapshot,
    )
    from ironsbot.services.seer.peak import PeakQueryService
    from ironsbot.services.seer.pet_query import PetQueryService
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_queries import RankQueryService
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.seer.type_query import TypeQueryService


class NewContentMenuRenderer(Protocol):
    async def __call__(  # noqa: PLR0913
        self,
        snapshot: NewContentSnapshot,
        display_categories: tuple[NewContentCategory, ...],
        focused_category: NewContentCategory | None,
        menu_title: str,
        expanded_categories: frozenset[NewContentCategory],
        auto_expand_max_items: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SeerQueryResources:
    data_queries: SeerDataQueryService
    countermark_rank: CountermarkStatRankService
    autocard: AutocardService
    autocard_sanctuary: AutocardSanctuaryService
    team_query: SeerTeamQueryService
    equipment: EquipmentQueryService
    type_query: TypeQueryService
    battle_effect: BattleEffectQueryService
    pet_query: PetQueryService
    peak_query: PeakQueryService
    mintmark: MintmarkQueryService
    player: PlayerService
    player_detail_extensions: PlayerDetailExtensionRegistry
    rank_queries: RankQueryService
    rank_admin: RankAdminService
    new_content_menu: NewContentMenuRenderer
    external_references: SeerInfoReferences
