import sqlite3
from pathlib import Path

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
    normalize_push_mode_text,
)
from ironsbot.services.identity_link_store import CrossPlatformGroupLink
from ironsbot.services.identity_principals import IdentityPrincipalService


def _official_group(app_id: str, openid: str) -> ConversationRef:
    return ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        openid,
        account_id=app_id,
    )


def test_bili_push_preference_store_sets_gets_and_clears_mode(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "bili_preferences.sqlite"
    store = SqliteBiliPushPreferenceStore(db_path)
    conversation = ConversationRef(Platform.ONEBOT, "group", "1001")

    assert store.get_mode(conversation, 123456) is None

    store.set_mode(conversation, 123456, "full")

    assert store.get_mode(conversation, 123456) == "full"

    with sqlite3.connect(db_path) as conn:
        indexes = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert "idx_bili_push_preferences_uid" in indexes

    store.clear_mode(conversation, 123456)

    assert store.get_mode(conversation, 123456) is None


def test_bili_push_subscription_key_and_mode_normalization() -> None:
    assert bili_push_subscription_key(123456) == "bili_push:123456"
    assert normalize_push_mode_text(" content ") == "full"
    assert normalize_push_mode_text("url") == "link"
    assert normalize_push_mode_text("default") is None


def test_bili_push_preference_store_persists_category_target_preferences(
    tmp_path: Path,
) -> None:
    store = SqliteBiliPushPreferenceStore(tmp_path / "bili_preferences.sqlite")

    group = ConversationRef(Platform.ONEBOT, "group", "1001")
    private = ConversationRef(Platform.ONEBOT, "private", "1001")
    assert store.category_muted(group, 123456, "lottery") is None

    store.set_category_muted(
        group,
        123456,
        "lottery",
        muted=True,
    )

    assert store.category_muted(group, 123456, "lottery") is True
    assert store.category_muted(private, 123456, "lottery") is None


def test_bili_preferences_merge_by_group_principal_and_latest_update(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    path = tmp_path / "bili_preferences.sqlite"
    store = SqliteBiliPushPreferenceStore(
        path,
        principal_for=principals.conversation_principal,
    )
    onebot = ConversationRef(Platform.ONEBOT, "group", "1001")
    official_a = _official_group("app-a", "group-a")
    official_b = _official_group("app-b", "group-b")

    store.set_mode(onebot, 123456, "full")
    store.set_category_muted(onebot, 123456, "lottery", muted=True)
    store.set_mode(official_a, 123456, "link")
    store.set_category_muted(official_a, 123456, "lottery", muted=False)
    with sqlite3.connect(path) as connection:
        for table in (
            "bili_push_preferences",
            "bili_push_category_preferences",
        ):
            connection.execute(
                f"UPDATE {table} SET updated_at = '2026-07-10T00:00:00+00:00' "
                "WHERE conversation_id = 'group-a'"
            )
            connection.execute(
                f"UPDATE {table} SET updated_at = '2026-07-09T00:00:00+00:00' "
                "WHERE conversation_id = '1001'"
            )

    for link in (
        CrossPlatformGroupLink("1001", "app-a", "group-a", 1.0),
        CrossPlatformGroupLink("1001", "app-b", "group-b", 2.0),
    ):
        for merge in principals.register_group_link(link):
            store.merge_principals(merge.source, merge.target)

    for conversation in (onebot, official_a, official_b):
        assert store.get_mode(conversation, 123456) == "link"
        assert store.category_muted(conversation, 123456, "lottery") is False
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT conversation_id FROM bili_push_preferences"
        ).fetchall() == [("group-a",)]
        assert connection.execute(
            "SELECT COUNT(*) FROM bili_push_category_preferences "
            "WHERE principal_kind = 'official_group'"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_v3_bili_preferences_migrate_to_principal_ownership(tmp_path: Path) -> None:
    path = tmp_path / "bili_preferences.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE bili_push_preferences (
                conversation_platform TEXT NOT NULL,
                conversation_account_id TEXT NOT NULL DEFAULT '',
                conversation_kind TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                uid INTEGER NOT NULL,
                mode TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id, uid
                )
            );
            CREATE TABLE bili_push_category_preferences (
                conversation_platform TEXT NOT NULL,
                conversation_account_id TEXT NOT NULL DEFAULT '',
                conversation_kind TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                uid INTEGER NOT NULL,
                category TEXT NOT NULL,
                muted INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id, uid, category
                )
            );
            CREATE TABLE ironsbot_schema_migrations (
                namespace TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO ironsbot_schema_migrations VALUES (
                'bilibili_preferences', 3, '2026-07-09T00:00:00+00:00'
            );
            INSERT INTO bili_push_preferences VALUES (
                'onebot', '', 'group', '1001', 123456, 'full',
                '2026-07-09T00:00:00+00:00'
            );
            INSERT INTO bili_push_category_preferences VALUES (
                'onebot', '', 'group', '1001', 123456, 'lottery', 1,
                '2026-07-09T00:00:00+00:00'
            );
            INSERT INTO bili_push_category_preferences VALUES (
                'onebot', '', 'group', '1001', 654321, 'lottery', 1,
                '2026-07-09T00:00:00+00:00'
            );
            INSERT INTO bili_push_category_preferences VALUES (
                'onebot', '', 'group', '1001', 654321, 'winning', 0,
                '2026-07-10T00:00:00+00:00'
            );
            """
        )

    store = SqliteBiliPushPreferenceStore(path)
    conversation = ConversationRef(Platform.ONEBOT, "group", "1001")

    assert store.get_mode(conversation, 123456) == "full"
    assert store.category_muted(conversation, 123456, "lottery") is True
    assert store.category_muted(conversation, 123456, "winning") is True
    assert store.category_muted(conversation, 654321, "lottery") is True
    assert store.category_muted(conversation, 654321, "winning") is False
    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(bili_push_preferences)"
            ).fetchall()
        }
        assert {"principal_kind", "principal_id"} <= columns
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
