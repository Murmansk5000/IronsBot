# SPDX-License-Identifier: GPL-3.0-or-later
"""Query-local evidence; never infer global ordering from a successful probe."""

from __future__ import annotations

import hashlib
import inspect
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from itertools import pairwise
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast
from uuid import uuid4

from ironsbot.core.rank_lookup_context import rank_query_id
from ironsbot.services.seer.rank_models import RankLookupResult, RankScoreSearchResult

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
P = ParamSpec("P")
T = TypeVar("T")


class RankOrderError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("榜单顺序异常，名次未确认")


@dataclass
class RankEvidence:
    enforce_order: bool = True
    pages: dict[tuple[int, int, int], list[tuple[int, int]]] = field(
        default_factory=dict
    )

    def observe(
        self,
        *,
        key: int,
        sub_key: int,
        start: int,
        rows: list[tuple[int, int]],
        excluded: frozenset[int],
    ) -> None:
        previous = self.pages.get((key, sub_key, start))
        self.pages[key, sub_key, start] = rows
        positions: dict[int, tuple[int, int]] = {}
        relevant = {
            page_start: page
            for (page_key, page_sub, page_start), page in self.pages.items()
            if (page_key, page_sub) == (key, sub_key)
        }
        inconsistent = previous is not None and (
            [row for row in previous if row[0] not in excluded]
            != [row for row in rows if row[0] not in excluded]
        )
        for page_start, page in relevant.items():
            for offset, row in enumerate(page):
                index = page_start + offset
                if (
                    index in positions
                    and positions[index] != row
                    and positions[index][0] not in excluded
                    and row[0] not in excluded
                ):
                    inconsistent = True
                positions[index] = row
        visible = [
            row for _, row in sorted(positions.items()) if row[0] not in excluded
        ]
        inverted = any(a[1] < b[1] for a, b in pairwise(visible))
        duplicate = len({row[0] for row in visible}) != len(visible)
        if not (inverted or duplicate or inconsistent):
            return
        logger.error(
            "rank evidence query=%s key=%s sub_key=%s inverted=%s duplicate=%s "
            "changed=%s pages=%s previous=%s",
            rank_query_id.get(),
            key,
            sub_key,
            inverted,
            duplicate,
            inconsistent,
            relevant,
            previous,
        )
        if self.enforce_order:
            raise RankOrderError


_evidence: ContextVar[RankEvidence | None] = ContextVar("rank_evidence", default=None)


def observe_rank_page(  # noqa: PLR0913
    policy: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    items: list[Any],
    fetched_at: float,
    cached: bool,
) -> None:
    rows = [(int(item.id), int(item.score)) for item in items]
    logger.info(
        "rank page query=%s key=%s sub_key=%s range=%s-%s count=%s "
        "source=%s fetched_at=%s first=%s last=%s decoded_sha256=%s",
        rank_query_id.get(),
        key,
        sub_key,
        start,
        end,
        len(rows),
        "cache" if cached else "online",
        fetched_at,
        rows[:1],
        rows[-1:],
        hashlib.sha256(repr(rows).encode("ascii")).hexdigest(),
    )
    evidence = _evidence.get()
    if evidence is not None:
        rank_key = policy.rank_key_for_protocol(key=key, sub_key=sub_key)
        evidence.observe(
            key=key,
            sub_key=sub_key,
            start=start,
            rows=rows,
            excluded=policy.excluded_user_ids(rank_key),
        )


def diagnose_rank_query(
    function: Callable[P, Awaitable[T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Give each public lookup its own evidence, including concurrent lookups."""
    signature = inspect.signature(function)

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        parameters = signature.bind(*args, **kwargs).arguments
        query_token = rank_query_id.set(uuid4().hex[:16])
        evidence = RankEvidence(
            enforce_order=function.__name__ != "fetch_visible_range_result"
        )
        evidence_token = _evidence.set(evidence)
        logger.info(
            "rank query start query=%s entry=%s user_id=%s key=%s sub_key=%s "
            "profile_score=%s strategy=%s",
            rank_query_id.get(),
            function.__name__,
            parameters.get("user_id"),
            parameters.get("key"),
            parameters.get("sub_key"),
            parameters.get("target_score"),
            "score_hint" if parameters.get("target_score") is not None else "id_lookup",
        )
        try:
            try:
                result = await function(*args, **kwargs)
            except RankOrderError as error:
                common = {
                    "title": parameters.get("title", "榜单"),
                    "score_name": parameters.get("score_name", ""),
                    "queried": True,
                    "failure": str(error),
                }
                result = cast(
                    "T",
                    (
                        RankScoreSearchResult(
                            **common, target_score=parameters["target_score"]
                        )
                        if function.__name__ == "fetch_score_segment"
                        else RankLookupResult(
                            **common, profile_score=parameters.get("target_score")
                        )
                    ),
                )
            if isinstance(result, RankLookupResult):
                result.query_id = rank_query_id.get()
                result.profile_score = parameters.get("target_score")
                if (
                    result.observed_score is not None
                    and result.profile_score is not None
                    and result.observed_score != result.profile_score
                ):
                    logger.error(
                        "rank score conflict query=%s profile=%s "
                        "rank_score=%s pages=%s",
                        rank_query_id.get(),
                        result.profile_score,
                        result.observed_score,
                        evidence.pages,
                    )
            logger.info(
                "rank query result query=%s status=%s result=%s",
                rank_query_id.get(),
                getattr(result, "status", "complete"),
                result
                if isinstance(result, RankLookupResult)
                else {
                    "count": len(getattr(result, "items", [])),
                    "failure": getattr(result, "failure", None),
                },
            )
            return result  # noqa: TRY300
        except BaseException as error:
            # Transport exception text can contain authentication parameters.
            logger.error(  # noqa: TRY400
                "rank query failed query=%s error=%s",
                rank_query_id.get(),
                type(error).__name__,
            )
            raise
        finally:
            _evidence.reset(evidence_token)
            rank_query_id.reset(query_token)

    return wrapped
