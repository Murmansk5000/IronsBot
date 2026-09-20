# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ironsbot.platform_state_migration as migration
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.storage.identity_links import (
    OfficialIdentity,
    SqliteIdentityLinkStore,
)
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.sqlite import SqliteMigrationError
from ironsbot.platform_state_migration import (
    PlatformStateMigrationError,
    migrate_platform_state_identities,
)
from ironsbot.state_migration_cli import main as state_migration_main

_OLD_PLAYER_ID = 90001
_NEW_PLAYER_ID = 90002


class SimulatedInterruptionError(RuntimeError):
    """Raised by the migration test to emulate an interrupted build."""


def _execute(path: Path, statements: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        for statement in statements:
            connection.execute(statement)
        connection.commit()


def _seed_legacy_platform_state(root: Path) -> None:
    _execute(
        root / "state/qq_state.sqlite",
        (
            """
            CREATE TABLE player_bindings (
                qq_user_id INTEGER PRIMARY KEY, player_id INTEGER, player_nick TEXT,
                choice_completed INTEGER NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, last_changed_at TEXT
            )
            """,
            """
            INSERT INTO player_bindings VALUES (
                1001, 90001, '示例玩家', 1, '2026-01-01T00:00:00Z',
                '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z'
            )
            """,
            """
            CREATE TABLE player_query_usage (
                local_date TEXT, qq_user_id INTEGER, scope TEXT, player_id INTEGER,
                action_key TEXT, usage_count INTEGER, updated_at TEXT
            )
            """,
            """
            INSERT INTO player_query_usage VALUES (
                '2026-08-04', 1001, 'bound_default', 0, 'all', 2,
                '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE lucky_skin_watch_preferences (
                qq_user_id INTEGER PRIMARY KEY, skin_ids_json TEXT,
                initialized_at TEXT, updated_at TEXT
            )
            """,
            """
            INSERT INTO lucky_skin_watch_preferences VALUES (
                1001, '[1400538]', '2026-08-04T00:00:00Z', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE push_unsubscriptions (
                target_type TEXT, target_id INTEGER, subscription_key TEXT,
                feature TEXT, created_at TEXT
            )
            """,
            """
            INSERT INTO push_unsubscriptions VALUES (
                'private', 1001, 'daily', 'feature', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE push_time_preferences (
                target_type TEXT, target_id INTEGER, subscription_key TEXT,
                preference_type TEXT, value TEXT, updated_at TEXT
            )
            """,
            """
            INSERT INTO push_time_preferences VALUES (
                'group', 2001, 'daily', 'cron_time', '23:00', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE push_daily_hints (
                target_type TEXT, target_id INTEGER, hint_key TEXT,
                delivered_on TEXT, updated_at TEXT
            )
            """,
            """
            INSERT INTO push_daily_hints VALUES (
                'private', 1001, 'hint', '2026-08-04', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE bili_push_preferences (
                target_type TEXT, target_id INTEGER, uid INTEGER, mode TEXT,
                updated_at TEXT
            )
            """,
            """
            INSERT INTO bili_push_preferences VALUES (
                'group', 2001, 123, 'full', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE bili_push_category_preferences (
                target_type TEXT, target_id INTEGER, uid INTEGER,
                category TEXT, muted INTEGER, updated_at TEXT
            )
            """,
            """
            INSERT INTO bili_push_category_preferences VALUES (
                'group', 2001, 123, 'lottery', 1,
                '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE group_rank_display_limits (
                group_id INTEGER PRIMARY KEY, display_limit INTEGER,
                updated_at TEXT, updated_by INTEGER
            )
            """,
            """
            INSERT INTO group_rank_display_limits VALUES (
                2001, 50, '2026-08-04T00:00:00Z', 1001
            )
            """,
            """
            CREATE TABLE team_resource_subscriptions (
                group_id INTEGER, team_id INTEGER, team_name TEXT, threshold INTEGER,
                at_user_ids TEXT, created_by INTEGER, updated_by INTEGER,
                created_at TEXT, updated_at TEXT
            )
            """,
            """
            INSERT INTO team_resource_subscriptions VALUES (
                2001, 3001, '示例战队', 1000, '1001,1002,1001', 1001, 1002,
                '2026-08-04T00:00:00Z', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE team_resource_private_subscriptions (
                user_id INTEGER, team_id INTEGER, team_name TEXT, threshold INTEGER,
                created_at TEXT, updated_at TEXT
            )
            """,
            """
            INSERT INTO team_resource_private_subscriptions VALUES (
                1001, 3001, '示例战队', 1000,
                '2026-08-04T00:00:00Z', '2026-08-04T00:00:00Z'
            )
            """,
            """
            CREATE TABLE team_resource_subscription_prompts (
                group_id INTEGER, team_id INTEGER, team_name TEXT, prompted_by INTEGER,
                prompted_at TEXT, handled_by INTEGER, handled_at TEXT, accepted INTEGER
            )
            """,
            """
            INSERT INTO team_resource_subscription_prompts VALUES (
                2001, 3001, '示例战队', 1001, '2026-08-04T00:00:00Z', 1002,
                '2026-08-04T00:01:00Z', 1
            )
            """,
        ),
    )
    _execute(
        root / "state/runtime_state.sqlite",
        (
            """
            CREATE TABLE pending_team_audit_reminders (
                group_id INTEGER, user_id INTEGER, joined_at TEXT,
                remind_at TEXT, step INTEGER
            )
            """,
            """
            INSERT INTO pending_team_audit_reminders VALUES (
                2001, 1001, '2026-08-04T00:00:00Z', '2026-08-05T00:00:00Z', 1
            )
            """,
            """
            CREATE TABLE sent_activity_reminders (
                activity_id INTEGER PRIMARY KEY, sent_at TEXT
            )
            """,
            "INSERT INTO sent_activity_reminders VALUES (1, '2026-08-04T00:00:00Z')",
        ),
    )
    _execute(
        root / "ai_chat/memory.sqlite",
        (
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, user_id INTEGER, session_key TEXT,
                chat_scope TEXT, chat_id INTEGER, role TEXT, content TEXT,
                created_at REAL
            )
            """,
            """
            INSERT INTO messages VALUES (
                1, 1001, 'session', 'private', 1001, 'user', '你好', 1.0
            )
            """,
        ),
    )


def _seed_accountless_qq_official_state(root: Path) -> None:
    marker = """
        CREATE TABLE ironsbot_platform_identity_migration (
            version INTEGER NOT NULL, migrated_at TEXT NOT NULL
        )
    """
    metadata = """
        CREATE TABLE ironsbot_schema_migrations (
            namespace TEXT PRIMARY KEY, version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """
    _execute(
        root / "state/qq_state.sqlite",
        (
            marker,
            metadata,
            "INSERT INTO ironsbot_platform_identity_migration VALUES (1, 'old')",
            "INSERT INTO ironsbot_schema_migrations VALUES "
            "('player_bindings', 1, 'old')",
            "INSERT INTO ironsbot_schema_migrations VALUES "
            "('team_resources', 1, 'old')",
            """
            CREATE TABLE player_bindings (
                actor_platform TEXT NOT NULL, actor_kind TEXT NOT NULL,
                actor_id TEXT NOT NULL, actor_scope_id TEXT NOT NULL DEFAULT '',
                player_id INTEGER, player_nick TEXT,
                choice_completed INTEGER NOT NULL DEFAULT 0,
                last_changed_at TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (actor_platform, actor_kind, actor_id, actor_scope_id)
            )
            """,
            """
            INSERT INTO player_bindings VALUES (
                'qq_official', 'user', 'same-openid', '', 90001, '旧机器人',
                1, NULL, 'old', 'old'
            )
            """,
            """
            CREATE TABLE team_resource_subscriptions (
                conversation_platform TEXT NOT NULL,
                conversation_kind TEXT NOT NULL, conversation_id TEXT NOT NULL,
                team_id INTEGER NOT NULL, team_name TEXT NOT NULL,
                threshold INTEGER NOT NULL, created_by_platform TEXT NOT NULL,
                created_by_kind TEXT NOT NULL, created_by_id TEXT NOT NULL,
                created_by_scope_id TEXT NOT NULL, updated_by_platform TEXT NOT NULL,
                updated_by_kind TEXT NOT NULL, updated_by_id TEXT NOT NULL,
                updated_by_scope_id TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            INSERT INTO team_resource_subscriptions VALUES (
                'qq_official', 'group', 'same-group-openid', 3001, '示例战队',
                1000, 'qq_official', 'user', 'same-openid', '',
                'qq_official', 'user', 'same-openid', '', 'old', 'old'
            )
            """,
            """
            CREATE TABLE team_resource_subscription_mentions (
                conversation_platform TEXT NOT NULL,
                conversation_kind TEXT NOT NULL, conversation_id TEXT NOT NULL,
                team_id INTEGER NOT NULL, actor_platform TEXT NOT NULL,
                actor_kind TEXT NOT NULL, actor_id TEXT NOT NULL,
                actor_scope_id TEXT NOT NULL, position INTEGER NOT NULL
            )
            """,
            """
            INSERT INTO team_resource_subscription_mentions VALUES (
                'qq_official', 'group', 'same-group-openid', 3001,
                'qq_official', 'user', 'same-openid', '', 0
            )
            """,
        ),
    )
    _execute(
        root / "state/runtime_state.sqlite",
        (
            marker,
            metadata,
            "INSERT INTO ironsbot_platform_identity_migration VALUES (1, 'old')",
            "INSERT INTO ironsbot_schema_migrations VALUES ('team_audit', 1, 'old')",
            """
            CREATE TABLE pending_team_audit_reminders (
                conversation_platform TEXT NOT NULL,
                conversation_kind TEXT NOT NULL, conversation_id TEXT NOT NULL,
                actor_platform TEXT NOT NULL, actor_kind TEXT NOT NULL,
                actor_id TEXT NOT NULL, actor_scope_id TEXT NOT NULL,
                joined_at TEXT NOT NULL, remind_at TEXT NOT NULL,
                step INTEGER NOT NULL
            )
            """,
            """
            INSERT INTO pending_team_audit_reminders VALUES (
                'qq_official', 'group', 'same-group-openid', 'qq_official',
                'member', 'same-openid', 'same-group-openid', 'old', 'old', 1
            )
            """,
        ),
    )
    _execute(
        root / "ai_chat/memory.sqlite",
        (
            marker,
            metadata,
            "INSERT INTO ironsbot_platform_identity_migration VALUES (1, 'old')",
            "INSERT INTO ironsbot_schema_migrations VALUES ('ai_memory', 1, 'old')",
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, actor_platform TEXT NOT NULL,
                actor_kind TEXT NOT NULL, actor_id TEXT NOT NULL,
                actor_scope_id TEXT NOT NULL, session_key TEXT NOT NULL,
                conversation_platform TEXT NOT NULL,
                conversation_kind TEXT NOT NULL, conversation_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO messages VALUES (
                1, 'qq_official', 'user', 'same-openid', '', 'session',
                'qq_official', 'private', 'same-openid', 'user', 'hello', 1.0
            )
            """,
        ),
    )


def test_platform_state_migration_dry_run_is_read_only(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)

    result = migrate_platform_state_identities(data_root=data_root)

    assert not result.applied
    assert not result.already_migrated
    assert result.migrated_rows["player_bindings"] == 1
    with sqlite3.connect(data_root / "state/qq_state.sqlite") as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(player_bindings)")
        }
    assert "qq_user_id" in columns
    assert "actor_id" not in columns
    assert not list(data_root.glob("platform-identity-migration-backups/*"))


def test_platform_state_migration_accepts_an_empty_data_root(tmp_path: Path) -> None:
    result = migrate_platform_state_identities(data_root=tmp_path / "data")

    assert not result.applied
    assert not result.already_migrated
    assert result.migrated_rows == {}


def test_platform_state_migration_rejects_an_unreadable_source(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    source = data_root / "state/qq_state.sqlite"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not a sqlite database")

    with pytest.raises(PlatformStateMigrationError, match="cannot read"):
        migrate_platform_state_identities(data_root=data_root)

    assert not list(data_root.glob("platform-identity-migration-backups/*"))


def test_platform_state_migration_converts_all_identity_shapes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)

    result = migrate_platform_state_identities(
        data_root=data_root,
        backup_root=tmp_path / "backups",
        apply=True,
        now=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert result.applied
    assert result.backup_path is not None
    backup_path = result.backup_path
    assert backup_path == tmp_path / "backups/20260804T000000Z"
    assert (backup_path / "state/qq_state.sqlite").is_file()
    with sqlite3.connect(data_root / "state/qq_state.sqlite") as connection:
        assert connection.execute(
            """
            SELECT actor_platform, actor_account_id, actor_kind, actor_id,
                   actor_scope_id, player_id
            FROM player_bindings
            """
        ).fetchall() == [("onebot", "", "user", "1001", "", 90001)]
        assert connection.execute(
            """
            SELECT conversation_kind, conversation_id
            FROM push_time_preferences
            """
        ).fetchall() == [("group", "2001")]
        assert connection.execute(
            """
            SELECT conversation_platform, conversation_account_id,
                   conversation_kind, conversation_id, uid, category, muted
            FROM bili_push_category_preferences
            """
        ).fetchall() == [("onebot", "", "group", "2001", 123, "lottery", 1)]
        assert connection.execute(
            """
            SELECT actor_id, position
            FROM team_resource_subscription_mentions
            ORDER BY position
            """
        ).fetchall() == [("1001", 0), ("1002", 1)]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(player_bindings)")
        }
    assert "qq_user_id" not in columns
    with sqlite3.connect(data_root / "state/runtime_state.sqlite") as connection:
        assert connection.execute(
            """
            SELECT conversation_id, actor_kind, actor_id, actor_scope_id
            FROM pending_team_audit_reminders
            """
        ).fetchall() == [("2001", "member", "1001", "2001")]
        assert connection.execute(
            "SELECT sent_at FROM sent_activity_reminders"
        ).fetchall() == [("2026-08-04T00:00:00Z",)]
    with sqlite3.connect(data_root / "ai_chat/memory.sqlite") as connection:
        assert connection.execute(
            """
            SELECT actor_id, conversation_kind, conversation_id, content
            FROM messages
            """
        ).fetchall() == [("1001", "private", "1001", "你好")]

    repeated = migrate_platform_state_identities(data_root=data_root, apply=True)
    assert repeated.already_migrated
    assert not repeated.applied


@pytest.mark.asyncio
async def test_platform_migration_preserves_explicit_identity_links(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)
    store = SqliteIdentityLinkStore(data_root / "state/qq_state.sqlite")
    official = OfficialIdentity("app-a", "member", "member-a", "group-a")
    await store.issue(
        token_hash="token-hash",
        onebot_qq_id="1001",
        official_app_id="app-a",
        created_at=1.0,
        expires_at=10.0,
    )
    await store.consume(token_hash="token-hash", official=official, now=2.0)

    result = migrate_platform_state_identities(data_root=data_root, apply=True)

    assert result.applied
    migrated = SqliteIdentityLinkStore(data_root / "state/qq_state.sqlite")
    links = await migrated.for_onebot("1001")
    assert len(links) == 1
    assert links[0].official == OfficialIdentity("app-a", "member", "member-a")


def test_platform_state_migration_rejects_invalid_target_type(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)
    _execute(
        data_root / "state/qq_state.sqlite",
        ("UPDATE push_unsubscriptions SET target_type = 'unsupported'",),
    )

    with pytest.raises(PlatformStateMigrationError, match="invalid target type"):
        migrate_platform_state_identities(data_root=data_root)

    assert not list(data_root.glob("platform-identity-migration-backups/*"))


def test_accountless_qq_official_state_requires_owning_app_id(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _seed_accountless_qq_official_state(data_root)

    with pytest.raises(
        PlatformStateMigrationError,
        match="requires its owning AppID",
    ):
        migrate_platform_state_identities(data_root=data_root)


def test_runtime_refuses_accountless_platform_identity_schema(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed_accountless_qq_official_state(data_root)
    store = SqlitePlayerBindingStore(data_root / "state/qq_state.sqlite")
    actor = ActorRef(Platform.QQ_OFFICIAL, "same-openid", account_id="app-a")

    with pytest.raises(SqliteMigrationError, match="requires offline"):
        store.get(actor)


def test_accountless_qq_official_state_is_scoped_and_allows_same_openid(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _seed_accountless_qq_official_state(data_root)

    result = migrate_platform_state_identities(
        data_root=data_root,
        qq_official_account_id="app-a",
        apply=True,
    )

    assert result.applied
    with sqlite3.connect(data_root / "state/qq_state.sqlite") as connection:
        assert connection.execute(
            """
            SELECT conversation_account_id, created_by_account_id,
                   updated_by_account_id
            FROM team_resource_subscriptions
            """
        ).fetchone() == ("app-a", "app-a", "app-a")
        assert connection.execute(
            """
            SELECT conversation_account_id, actor_account_id
            FROM team_resource_subscription_mentions
            """
        ).fetchone() == ("app-a", "app-a")
    with sqlite3.connect(data_root / "state/runtime_state.sqlite") as connection:
        assert connection.execute(
            """
            SELECT conversation_account_id, actor_account_id
            FROM pending_team_audit_reminders
            """
        ).fetchone() == ("app-a", "app-a")
    with sqlite3.connect(data_root / "ai_chat/memory.sqlite") as connection:
        assert connection.execute(
            """
            SELECT actor_account_id, conversation_account_id FROM messages
            """
        ).fetchone() == ("app-a", "app-a")
    store = SqlitePlayerBindingStore(data_root / "state/qq_state.sqlite")
    actor_a = ActorRef(
        Platform.QQ_OFFICIAL,
        "same-openid",
        account_id="app-a",
    )
    actor_b = ActorRef(
        Platform.QQ_OFFICIAL,
        "same-openid",
        account_id="app-b",
    )
    assert store.get(actor_a).player_id == _OLD_PLAYER_ID
    assert store.get(actor_b).player_id is None

    store.bind(actor=actor_b, player_id=_NEW_PLAYER_ID, player_nick="新机器人")

    assert store.get(actor_a).player_id == _OLD_PLAYER_ID
    assert store.get(actor_b).player_id == _NEW_PLAYER_ID


def test_platform_state_migration_preserves_sources_when_build_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)
    source = data_root / "state/qq_state.sqlite"
    original = source.read_bytes()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise SimulatedInterruptionError

    monkeypatch.setattr(migration, "_build_targets", fail)

    with pytest.raises(SimulatedInterruptionError):
        migrate_platform_state_identities(data_root=data_root, apply=True)

    assert source.read_bytes() == original
    assert not migration.table_exists(source, "ironsbot_platform_identity_migration")


def test_platform_state_migration_rejects_duplicate_target_keys(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    path = data_root / "state/qq_state.sqlite"
    _execute(
        path,
        (
            """
            CREATE TABLE player_bindings (
                qq_user_id INTEGER, player_id INTEGER, player_nick TEXT,
                choice_completed INTEGER, created_at TEXT, updated_at TEXT,
                last_changed_at TEXT
            )
            """,
            """
            INSERT INTO player_bindings VALUES
            (1001, 1, '甲', 1, 'a', 'a', 'a'),
            (1001, 2, '乙', 1, 'b', 'b', 'b')
            """,
        ),
    )

    with pytest.raises(PlatformStateMigrationError, match="UNIQUE constraint failed"):
        migrate_platform_state_identities(data_root=data_root)


def test_platform_install_failure_restores_each_database_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)
    originals = {path: path.read_bytes() for path in data_root.rglob("*.sqlite")}
    original_replace = Path.replace
    target_runtime = data_root / "state/runtime_state.sqlite"

    def fail_runtime_install(path: Path, target: Path) -> Path:
        if target == target_runtime and ".platform-migrating-" in path.name:
            raise PermissionError
        return original_replace(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_runtime_install)
        with pytest.raises(PermissionError):
            migrate_platform_state_identities(data_root=data_root, apply=True)

    for path, original in originals.items():
        assert path.read_bytes() == original
        assert not migration.table_exists(path, "ironsbot_platform_identity_migration")
    assert not list(data_root.rglob("*.platform-migrating-*"))
    assert list(data_root.glob("platform-identity-migration-backups/*/manifest.json"))
    assert migrate_platform_state_identities(data_root=data_root, apply=True).applied


def test_state_migration_cli_exposes_platform_identity_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)

    exit_code = state_migration_main(
        (
            "--data-root",
            str(data_root),
            "--platform-identities",
        )
    )

    assert exit_code == 0
    assert "Dry run only; no files were changed." in capsys.readouterr().out


def test_state_migration_cli_accepts_qq_official_account_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    _seed_accountless_qq_official_state(data_root)

    exit_code = state_migration_main(
        (
            "--data-root",
            str(data_root),
            "--platform-identities",
            "--qq-official-account-id",
            "app-a",
        )
    )

    assert exit_code == 0
    assert "Dry run only; no files were changed." in capsys.readouterr().out


def test_state_migration_cli_reports_corrupt_identity_input_without_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_root = tmp_path / "data"
    _seed_legacy_platform_state(data_root)
    path = data_root / "state/qq_state.sqlite"
    _execute(path, ("UPDATE push_unsubscriptions SET target_type = 'invalid'",))
    original = path.read_bytes()
    assert (
        state_migration_main(
            ("--data-root", str(data_root), "--platform-identities", "--apply")
        )
        == 1
    )
    assert "Platform identity migration failed" in capsys.readouterr().err
    assert path.read_bytes() == original
    assert not list(data_root.glob("platform-identity-migration-backups/*"))
