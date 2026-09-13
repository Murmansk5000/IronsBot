from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from ironsbot.integrations.seer_data.data_query_repository import (
    PublishedDataQueryRepository,
)
from ironsbot.services.seer.data_query_facts import (
    PeakSeasonTimes,
    WeeklyPreviewLinks,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session

    from ironsbot.services.seer.data import DataQuery, SeerDataReader


GENERATED_AT = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
SEASON_END = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)


class _Result:
    def first(self) -> object:
        return SimpleNamespace(generate_time=GENERATED_AT)


class _Rows:
    def all(self) -> list[tuple[str, str]]:
        return [
            ("weekly_preview_image_url", "https://example.test/preview.png"),
            ("weekly_preview_source_url", "https://example.test/source"),
        ]


class _Session:
    def execute(self, _statement: object, _parameters: object) -> _Rows:
        return _Rows()

    def exec(self, _statement: object) -> _Result:
        return _Result()

    def get(self, _model: object, _key: int) -> object:
        return SimpleNamespace(start_time=None, end_time=SEASON_END)


class _Reader:
    @contextmanager
    def query(self, operation: DataQuery[object]) -> Iterator[object]:
        yield operation(cast("Session", _Session()))


def test_published_data_query_repository_detaches_domain_facts() -> None:
    repository = PublishedDataQueryRepository(cast("SeerDataReader", _Reader()))

    assert repository.weekly_preview_links() == WeeklyPreviewLinks(
        "https://example.test/preview.png",
        "https://example.test/source",
    )
    assert repository.generated_at() == GENERATED_AT
    assert repository.peak_season_times() == PeakSeasonTimes(None, SEASON_END)
