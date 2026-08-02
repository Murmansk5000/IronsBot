from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from ironsbot.state_migration import StateMigrationError, migrate_state_databases

if TYPE_CHECKING:
    from pathlib import Path

LEGACY_PRIVATE_UNSUBSCRIPTION_COUNT = 2


def _execute(path: Path, statements: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        for statement in statements:
            connection.execute(statement)


def _seed_legacy_state(root: Path) -> None:
    _execute(
        root / "seer/player_bindings.sqlite",
        (
            """
            CREATE TABLE player_bindings (
                qq_user_id INTEGER PRIMARY KEY,
                player_id INTEGER,
                player_nick TEXT,
                choice_completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_changed_at TEXT
            )
            """,
            """
            INSERT INTO player_bindings VALUES (
                1234567890, 148758762, '示例玩家', 1,
                '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z',
                '2026-01-02T00:00:00Z'
            )
            """,
        ),
    )
    _execute(
        root / "messaging/push_unsubscriptions.sqlite",
        (
            """
            CREATE TABLE push_unsubscriptions (
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                subscription_key TEXT NOT NULL,
                feature TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (target_type, target_id, subscription_key)
            )
            """,
            """
            INSERT INTO push_unsubscriptions VALUES (
                'private', 1234567890, 'daily', 'new_feature',
                '2026-01-02T00:00:00Z'
            )
            """,
        ),
    )
    _execute(
        root / "messaging/private_push_unsubscriptions.sqlite",
        (
            """
            CREATE TABLE private_push_unsubscriptions (
                user_id INTEGER NOT NULL,
                schedule_key TEXT NOT NULL,
                feature TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, schedule_key)
            )
            """,
            """
            INSERT INTO private_push_unsubscriptions VALUES (
                1234567890, 'daily', 'old_feature', '2026-01-01T00:00:00Z'
            )
            """,
            """
            INSERT INTO private_push_unsubscriptions VALUES (
                1234567890, 'legacy-only', 'legacy_feature',
                '2026-01-01T00:00:00Z'
            )
            """,
        ),
    )
    _execute(
        root / "activity_reminder/sent.sqlite",
        (
            """
            CREATE TABLE sent_activity_reminders (
                activity_id INTEGER NOT NULL,
                end_time TEXT NOT NULL,
                lead_hours INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (activity_id, end_time, lead_hours)
            )
            """,
            """
            INSERT INTO sent_activity_reminders VALUES (
                7, '2026-08-08T10:00:00+08:00', 1,
                '2026-08-08T09:00:00+08:00'
            )
            """,
        ),
    )
    _execute(
        root / "seer/lucky_skin_window.sqlite",
        (
            """
            CREATE TABLE lucky_skin_window_daily_cache (
                day TEXT PRIMARY KEY,
                skin_ids_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """,
            """
            INSERT INTO lucky_skin_window_daily_cache VALUES (
                '2026-08-01', '[1,2,3,4]', '2026-08-01T00:02:00+08:00'
            )
            """,
        ),
    )
    _execute(
        root / "messaging/reply_limits.sqlite",
        ("CREATE TABLE group_reply_line_limits (group_id INTEGER PRIMARY KEY)",),
    )


def test_state_migration_dry_run_does_not_write(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_state(data_root)

    result = migrate_state_databases(data_root=data_root)

    assert not result.applied
    assert not result.already_migrated
    assert result.migrated_rows["player_bindings"] == 1
    assert (
        result.migrated_rows["private_push_unsubscriptions"]
        == LEGACY_PRIVATE_UNSUBSCRIPTION_COUNT
    )
    assert not (data_root / "state/qq_state.sqlite").exists()
    assert (data_root / "seer/player_bindings.sqlite").exists()


def test_state_migration_applies_and_archives_legacy_files(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    backup_root = tmp_path / "backups"
    _seed_legacy_state(data_root)

    result = migrate_state_databases(
        data_root=data_root,
        backup_root=backup_root,
        apply=True,
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )

    assert result.applied
    assert result.backup_path is not None
    assert result.backup_path == backup_root / "20260802T000000Z"
    qq_state = data_root / "state/qq_state.sqlite"
    runtime_state = data_root / "state/runtime_state.sqlite"
    assert qq_state.exists()
    assert runtime_state.exists()
    assert not (data_root / "seer/player_bindings.sqlite").exists()
    assert not (data_root / "messaging/reply_limits.sqlite").exists()
    assert (
        result.backup_path / "legacy/seer/player_bindings.sqlite"
    ).exists()
    assert (result.backup_path / "manifest.json").exists()

    with sqlite3.connect(qq_state) as connection:
        assert connection.execute(
            "SELECT player_id, player_nick FROM player_bindings"
        ).fetchall() == [(148758762, "示例玩家")]
        assert connection.execute(
            "SELECT subscription_key, feature FROM push_unsubscriptions "
            "ORDER BY subscription_key"
        ).fetchall() == [
            ("daily", "new_feature"),
            ("legacy-only", "legacy_feature"),
        ]
        namespaces = {
            str(row[0])
            for row in connection.execute(
                "SELECT namespace FROM ironsbot_schema_migrations"
            )
        }
        assert namespaces == {
            "bilibili_preferences",
            "player_bindings",
            "player_query_limits",
            "push_subscriptions",
            "rank_display",
            "team_resources",
        }

    with sqlite3.connect(runtime_state) as connection:
        assert connection.execute(
            "SELECT activity_id FROM sent_activity_reminders"
        ).fetchall() == [(7,)]
        assert connection.execute(
            "SELECT skin_ids_json FROM lucky_skin_window_daily_cache"
        ).fetchall() == [("[1,2,3,4]",)]
        namespaces = {
            str(row[0])
            for row in connection.execute(
                "SELECT namespace FROM ironsbot_schema_migrations"
            )
        }
        assert namespaces == {"activity_reminder", "skin_window", "team_audit"}

    repeated = migrate_state_databases(data_root=data_root, apply=True)
    assert repeated.already_migrated
    assert not repeated.applied


def test_state_migration_rejects_legacy_files_beside_new_state(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_state(data_root)
    migrate_state_databases(data_root=data_root, apply=True)
    _execute(
        data_root / "seer/player_bindings.sqlite",
        ("CREATE TABLE player_bindings (qq_user_id INTEGER PRIMARY KEY)",),
    )

    with pytest.raises(StateMigrationError, match="legacy files remain"):
        migrate_state_databases(data_root=data_root)


def test_state_migration_rejects_unrelated_existing_targets(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    qq_state = data_root / "state/qq_state.sqlite"
    runtime_state = data_root / "state/runtime_state.sqlite"
    _execute(qq_state, ("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)",))
    _execute(runtime_state, ("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)",))

    with pytest.raises(StateMigrationError, match="migration namespaces"):
        migrate_state_databases(data_root=data_root)
