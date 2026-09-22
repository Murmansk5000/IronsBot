# SPDX-License-Identifier: MIT
"""One address per AppID/OpenID, with independently observed transport types."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.identity_link_store import OfficialIdentity
from ironsbot.services.official_addresses import OfficialAddress

_MIGRATIONS = (
    SqliteMigration(
        1,
        (
            """
CREATE TABLE official_user_addresses (
    app_id TEXT NOT NULL,
    openid TEXT NOT NULL,
    member_seen_at REAL,
    private_seen_at REAL,
    PRIMARY KEY (app_id, openid)
)
""",
        ),
    ),
)


@dataclass(slots=True)
class SqliteOfficialAddressStore:
    path: Path
    _database: SqliteDatabase = field(init=False)

    def __post_init__(self) -> None:
        self._database = SqliteDatabase(
            self.path,
            migrations=_MIGRATIONS,
            migration_namespace="official_user_addresses",
        )

    async def observe(
        self, identity: OfficialIdentity, *, now: float
    ) -> OfficialAddress:
        return await asyncio.to_thread(self._observe, identity, now)

    def _observe(self, identity: OfficialIdentity, now: float) -> OfficialAddress:
        if identity.kind not in {"member", "user"}:
            raise ValueError(identity.kind)
        column = "member_seen_at" if identity.kind == "member" else "private_seen_at"
        with self._database.connect() as connection:
            connection.execute(
                f"INSERT INTO official_user_addresses (app_id, openid, {column}) "
                f"VALUES (?, ?, ?) ON CONFLICT (app_id, openid) DO UPDATE SET "
                f"{column}=MAX(COALESCE({column}, excluded.{column}), "
                f"excluded.{column})",
                (identity.app_id, identity.openid, now),
            )
            row = connection.execute(
                "SELECT app_id, openid, member_seen_at, private_seen_at "
                "FROM official_user_addresses WHERE app_id=? AND openid=?",
                (identity.app_id, identity.openid),
            ).fetchone()
        assert row is not None
        return OfficialAddress(
            row[0], row[1], row[2] is not None, row[3] is not None, row[2], row[3]
        )

    async def all_addresses(self) -> tuple[OfficialAddress, ...]:
        return await asyncio.to_thread(self._all)

    def _all(self) -> tuple[OfficialAddress, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT app_id, openid, member_seen_at, private_seen_at "
                "FROM official_user_addresses"
            ).fetchall()
        return tuple(
            OfficialAddress(a, o, m is not None, p is not None, m, p)
            for a, o, m, p in rows
        )
