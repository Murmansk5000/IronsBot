# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator

QueryWorkScope = Literal["foreground", "prefetch", "background_refresh", "cache"]

_current_meter: ContextVar[QueryWorkMeter | None] = ContextVar(
    "seer_query_work_meter",
    default=None,
)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueryWorkResult:
    """Logical server work observed while producing one user-facing reply."""

    scope: QueryWorkScope = "cache"
    successful_units: frozenset[str] = frozenset()
    failed_units: frozenset[str] = frozenset()
    cached_units: frozenset[str] = frozenset()

    @property
    def is_foreground(self) -> bool:
        return self.scope == "foreground"

    @property
    def billable_units(self) -> frozenset[str]:
        if not self.is_foreground:
            return frozenset()
        successful = self.successful_units
        billed = {
            unit
            for unit in successful
            if unit not in {"profile", "profile_extra", "online_status", "team_info"}
        }
        if successful & {"profile", "profile_extra", "online_status", "team_info"}:
            billed.add("basic_info")
        return frozenset(billed)


@dataclass(slots=True)
class QueryWorkMeter:
    """Context-local ledger for logical, rather than packet-level, work."""

    scope: QueryWorkScope
    _successful: set[str] = field(default_factory=set)
    _failed: set[str] = field(default_factory=set)
    _cached: set[str] = field(default_factory=set)

    def succeeded(self, unit: str) -> None:
        self._successful.add(unit)
        self._failed.discard(unit)

    def failed(self, unit: str) -> None:
        self._successful.discard(unit)
        self._failed.add(unit)

    def cached(self, unit: str) -> None:
        self._successful.discard(unit)
        self._failed.discard(unit)
        self._cached.add(unit)

    def result(self) -> QueryWorkResult:
        return QueryWorkResult(
            scope=self.scope,
            successful_units=frozenset(self._successful),
            failed_units=frozenset(self._failed),
            cached_units=frozenset(self._cached),
        )


@contextmanager
def query_work_scope(meter: QueryWorkMeter) -> Iterator[QueryWorkMeter]:
    token = _current_meter.set(meter)
    try:
        yield meter
    finally:
        _current_meter.reset(token)


def record_successful_query_work(unit: str) -> None:
    if (meter := _current_meter.get()) is not None:
        meter.succeeded(unit)


def record_failed_query_work(unit: str) -> None:
    if (meter := _current_meter.get()) is not None:
        meter.failed(unit)


def record_cached_query_work(unit: str) -> None:
    if (meter := _current_meter.get()) is not None:
        meter.cached(unit)


def record_rank_lookup_work(rank_key: str, result: object) -> None:
    """Record only a completed rank conclusion that touched the live server."""

    failure = getattr(result, "failure", None)
    cost = getattr(result, "cost", None)
    if failure is not None or bool(getattr(cost, "restricted_miss", False)):
        record_failed_query_work(f"rank:{rank_key}")
        return
    if bool(getattr(cost, "lightweight_confirmed", False)):
        record_cached_query_work(f"rank:{rank_key}")
        return
    if int(getattr(cost, "online_page_fetches", 0)) > 0:
        record_successful_query_work(f"rank:{rank_key}")
    else:
        record_cached_query_work(f"rank:{rank_key}")


async def run_with_query_work(
    meter: QueryWorkMeter,
    operation: Awaitable[T],
) -> T:
    with query_work_scope(meter):
        return await operation
