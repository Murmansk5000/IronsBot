# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.services.seer.query_work import (
    QueryWorkMeter,
    query_work_scope,
    record_cached_query_work,
    record_failed_query_work,
    record_successful_query_work,
)


def test_foreground_meter_collapses_base_profile_work_to_one_unit() -> None:
    meter = QueryWorkMeter("foreground")

    with query_work_scope(meter):
        for unit in ("profile", "profile_extra", "online_status", "team_info"):
            record_successful_query_work(unit)

    assert meter.result().billable_units == frozenset(("basic_info",))


def test_failed_rank_does_not_charge_pages_that_completed_before_timeout() -> None:
    meter = QueryWorkMeter("foreground")

    with query_work_scope(meter):
        record_successful_query_work("rank:peak_standard")
        record_failed_query_work("rank:peak_standard")

    result = meter.result()
    assert result.successful_units == frozenset()
    assert result.failed_units == frozenset(("rank:peak_standard",))
    assert result.billable_units == frozenset()


def test_cached_and_prefetch_work_are_not_billable() -> None:
    foreground = QueryWorkMeter("foreground")
    with query_work_scope(foreground):
        record_cached_query_work("rank:autocard")

    prefetch = QueryWorkMeter("prefetch")
    with query_work_scope(prefetch):
        record_successful_query_work("rank:autocard")

    assert foreground.result().billable_units == frozenset()
    assert prefetch.result().billable_units == frozenset()


def test_cached_rank_confirmation_reclassifies_earlier_page_work() -> None:
    meter = QueryWorkMeter("foreground")

    with query_work_scope(meter):
        record_successful_query_work("rank:autocard")
        record_cached_query_work("rank:autocard")

    assert meter.result().billable_units == frozenset()
