# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from threading import Lock, get_ident
from typing import TYPE_CHECKING, Any, cast

import pytest
import sqlmodel

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine


_original_sqlite_connect = sqlite3.connect
_original_create_engine = sqlmodel.create_engine


class _TestDatabaseResources:
    def __init__(self) -> None:
        self._lock = Lock()
        self._owner_thread: int | None = None
        self._connections: list[sqlite3.Connection] | None = None
        self._engines: list[Engine] | None = None

    def begin(self) -> None:
        with self._lock:
            self._owner_thread = get_ident()
            self._connections = []
            self._engines = []

    def add_connection(self, connection: sqlite3.Connection) -> None:
        with self._lock:
            if self._connections is not None and self._owner_thread == get_ident():
                self._connections.append(connection)

    def add_engine(self, engine: Engine) -> None:
        with self._lock:
            if self._engines is not None:
                self._engines.append(engine)

    def close(self) -> None:
        with self._lock:
            connections = self._connections
            engines = self._engines
            self._owner_thread = None
            self._connections = None
            self._engines = None
        for engine in reversed(engines or ()):
            engine.dispose()
        for connection in reversed(connections or ()):
            connection.close()


_database_resources = _TestDatabaseResources()


def _tracked_sqlite_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
    connection = _original_sqlite_connect(*args, **kwargs)
    _database_resources.add_connection(connection)
    return connection


def _tracked_create_engine(*args: Any, **kwargs: Any) -> Engine:
    engine = _original_create_engine(*args, **kwargs)
    _database_resources.add_engine(engine)
    return engine


sqlite3.connect = cast("Any", _tracked_sqlite_connect)
sqlmodel.create_engine = cast("Any", _tracked_create_engine)


@pytest.fixture(autouse=True)
def close_test_database_resources() -> Iterator[None]:
    """Give every test-owned database resource one deterministic owner."""

    _database_resources.begin()
    try:
        yield
    finally:
        _database_resources.close()
