from __future__ import annotations

import pytest
from sqlalchemy import event
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.services.operations.data_update import DataVersion


@pytest.mark.parametrize("registered", [False, True])
def test_unloaded_description_does_not_query_missing_business_tables(
    *,
    registered: bool,
) -> None:
    databases = DatabaseManager()
    if registered:
        databases.register("seerapi")
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    engine = databases.get_engine("seerapi")
    queries: list[str] = []
    if engine is not None:
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _c, _u, statement, *_args: queries.append(statement),
        )
    try:
        assert data.update_description() == DataVersion("unknown")
        assert not any(
            "api_metadata" in query or "peak_season" in query for query in queries
        )
    finally:
        databases.close()
