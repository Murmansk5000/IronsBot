# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart

if TYPE_CHECKING:
    from ironsbot.core.semantic_requests import ActionDefinition, SemanticTarget
    from ironsbot.services.seer.query_work import QueryWorkResult
    from ironsbot.services.seer.rank_models import RankLookupResult

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueryReply:
    leading_text: str = ""
    text: str = ""
    image: bytes | None = None
    image_error: str = ""
    rank_lookups: tuple[RankLookupResult, ...] = ()
    query_work: QueryWorkResult | None = None
    # Partial replies are deliverable but cannot populate the complete-reply cache.
    complete: bool = True
    fetched_at: float | None = None

    def to_outbound(self) -> OutboundMessage:
        parts: list[TextPart | BinaryImagePart] = []
        if self.leading_text:
            parts.append(TextPart(self.leading_text))
        if self.image is not None:
            parts.append(BinaryImagePart(self.image, "image/png"))
        elif self.image_error:
            parts.append(TextPart(self.image_error))
        if self.text:
            parts.append(TextPart(self.text))
        return OutboundMessage(tuple(parts))

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
    semantic_action: ActionDefinition | None = None


@dataclass(frozen=True, slots=True)
class QueryResult(Generic[T]):
    reply: QueryReply | None = None
    choices: tuple[QueryChoice[T], ...] = ()
    message: str = ""
