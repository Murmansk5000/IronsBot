# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from ironsbot.core.semantic_requests import SemanticTarget
    from ironsbot.services.seer.rank_models import RankLookupResult

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueryReply:
    leading_text: str = ""
    text: str = ""
    image: bytes | None = None
    image_error: str = ""
    rank_lookups: tuple[RankLookupResult, ...] = ()

    @property
    def rank_lookup_complete(self) -> bool:
        return bool(self.rank_lookups) and all(
            result.failure is None and not result.cost.restricted_miss
            for result in self.rank_lookups
        )

    @property
    def rank_lookup_is_lightweight(self) -> bool:
        return self.rank_lookup_complete and all(
            result.cost.lightweight_confirmed for result in self.rank_lookups
        )

    @property
    def rank_lookup_should_charge_quota(self) -> bool:
        # Shortcut implementations without rank-cost metadata retain the
        # historical successful-query quota behavior. Only an explicit,
        # complete set of anchor-page confirmations is free.
        return not self.rank_lookups or (
            self.rank_lookup_complete and not self.rank_lookup_is_lightweight
        )


@dataclass(frozen=True, slots=True)
class QueryChoice(Generic[T]):
    name: str
    description: str
    value: T
    is_sub_choice: bool = False
    semantic_target: SemanticTarget | None = None


@dataclass(frozen=True, slots=True)
class QueryResult(Generic[T]):
    reply: QueryReply | None = None
    choices: tuple[QueryChoice[T], ...] = ()
    message: str = ""
