from typing import Any

from ironsbot.services.activity.repository import ActivityRepository


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class FakeSession:
    def __init__(
        self,
        *,
        columns: list[str],
        rows: list[dict[str, object]],
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.queries: list[str] = []

    def execute(self, statement: Any) -> FakeResult:
        query = str(statement)
        self.queries.append(query)
        if "PRAGMA table_info(activity)" in query:
            return FakeResult([{"name": column} for column in self.columns])
        return FakeResult(self.rows)


def _load(session: FakeSession | None, *, only_shown: bool) -> list[Any]:
    return ActivityRepository().load(session, only_shown=only_shown)


def test_load_activity_rows_queries_expected_columns() -> None:
    session = FakeSession(
        columns=["id", "name", "start_time", "end_time", "is_show", "sort_order"],
        rows=[
            {
                "id": 1,
                "name": "审判天使",
                "start_time": "2026-06-05 10:00:00",
                "end_time": "2026-07-03 10:00:00",
                "is_show": 1,
                "sort_order": 1,
            }
        ],
    )

    rows = _load(
        session,
        only_shown=True,
    )

    assert rows == session.rows
    assert "start_time" in session.queries[-1]
    assert "COALESCE(is_show, 0) != 0" in session.queries[-1]


def test_load_activity_rows_allows_hidden_rows_when_requested() -> None:
    session = FakeSession(
        columns=["id", "name", "end_time", "is_show", "sort_order"],
        rows=[],
    )

    _load(
        session,
        only_shown=False,
    )

    assert "COALESCE(is_show, 0) != 0" not in session.queries[-1]
    assert "start_time" not in session.queries[-1]


def test_load_activity_rows_returns_empty_for_missing_session() -> None:
    assert (
        _load(
            None,
            only_shown=True,
        )
        == []
    )


def test_load_activity_rows_returns_empty_for_invalid_schema() -> None:
    session = FakeSession(columns=["id", "name"], rows=[])

    assert (
        _load(
            session,
            only_shown=True,
        )
        == []
    )
