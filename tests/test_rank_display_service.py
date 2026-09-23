import sqlite3
from pathlib import Path

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.services.identity_link_store import CrossPlatformGroupLink
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.seer.rank_display import RankDisplayService

GROUP_ID = 987654321
USER_ID = 1234567890
STORED_LIMIT = 50
NEWER_LIMIT = 40
ALIAS_LIMIT = 30
DEFAULT_LIMIT = 10


def _group(group_id: int = GROUP_ID) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _actor(user_id: int = USER_ID) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _rank_config() -> RankQueryConfig:
    return RankQueryConfig(
        display_limit=DEFAULT_LIMIT,
        max_display_limit=100,
        display_limits={},
    )


def _service(
    config: RankQueryConfig,
    configured_limits: dict[ConversationRef, int],
    state_path: Path,
) -> RankDisplayService:
    return RankDisplayService(
        config,
        configured_limits,
        SqliteRankDisplayStore(state_path),
    )


def test_rank_display_limit_prefers_stored_group_limit(
    tmp_path: Path,
) -> None:
    service = _service(_rank_config(), {}, tmp_path / "qq_state.sqlite")

    service.set_conversation_limit(
        _group(),
        _actor(),
        limit=STORED_LIMIT,
    )

    assert service.limit_for_conversation(_group()) == STORED_LIMIT


def test_rank_display_limit_uses_configured_alias(
    tmp_path: Path,
) -> None:
    service = _service(
        _rank_config(),
        {_group(): ALIAS_LIMIT},
        tmp_path / "qq_state.sqlite",
    )

    assert service.limit_for_conversation(_group()) == ALIAS_LIMIT


def test_rank_display_limits_are_isolated_by_platform(tmp_path: Path) -> None:
    service = _service(_rank_config(), {}, tmp_path / "qq_state.sqlite")
    onebot_group = _group()
    official_group = ConversationRef(Platform.QQ_OFFICIAL, "group", str(GROUP_ID))

    service.set_conversation_limit(onebot_group, _actor(), STORED_LIMIT)

    assert service.limit_for_conversation(onebot_group) == STORED_LIMIT
    assert service.limit_for_conversation(official_group) == DEFAULT_LIMIT


def test_rank_display_limit_merges_to_shared_group_by_latest_update(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    path = tmp_path / "qq_state.sqlite"
    store = SqliteRankDisplayStore(
        path,
        principal_for=principals.conversation_principal,
    )
    service = RankDisplayService(_rank_config(), {}, store)
    onebot = _group()
    official_a = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-a",
        account_id="app-a",
    )
    official_b = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-b",
        account_id="app-b",
    )
    service.set_conversation_limit(onebot, _actor(1), 20)
    service.set_conversation_limit(
        official_a,
        ActorRef(Platform.QQ_OFFICIAL, "member-a", account_id="app-a"),
        NEWER_LIMIT,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE group_rank_display_limits "
            "SET updated_at = '2026-07-09T00:00:00+00:00' "
            "WHERE conversation_id = ?",
            (onebot.id,),
        )
        connection.execute(
            "UPDATE group_rank_display_limits "
            "SET updated_at = '2026-07-10T00:00:00+00:00' "
            "WHERE conversation_id = ?",
            (official_a.id,),
        )

    for link in (
        CrossPlatformGroupLink(onebot.id, "app-a", official_a.id, 1.0),
        CrossPlatformGroupLink(onebot.id, "app-b", official_b.id, 2.0),
    ):
        for merge in principals.register_group_link(link):
            store.merge_principals(merge.source, merge.target)

    assert service.limit_for_conversation(onebot) == NEWER_LIMIT
    assert service.limit_for_conversation(official_a) == NEWER_LIMIT
    assert service.limit_for_conversation(official_b) == NEWER_LIMIT
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT conversation_id, updated_by_id FROM group_rank_display_limits"
        ).fetchall() == [(official_a.id, "member-a")]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_v2_rank_display_migrates_to_principal_ownership(tmp_path: Path) -> None:
    path = tmp_path / "qq_state.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE group_rank_display_limits (
                conversation_platform TEXT NOT NULL,
                conversation_account_id TEXT NOT NULL DEFAULT '',
                conversation_kind TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                display_limit INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by_platform TEXT NOT NULL,
                updated_by_account_id TEXT NOT NULL DEFAULT '',
                updated_by_kind TEXT NOT NULL,
                updated_by_id TEXT NOT NULL,
                updated_by_scope_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id
                )
            );
            CREATE TABLE ironsbot_schema_migrations (
                namespace TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO ironsbot_schema_migrations VALUES (
                'rank_display', 2, '2026-07-09T00:00:00+00:00'
            );
            INSERT INTO group_rank_display_limits VALUES (
                'onebot', '', 'group', '987654321', 50,
                '2026-07-09T00:00:00+00:00',
                'onebot', '', 'user', '1234567890', ''
            );
            """
        )

    store = SqliteRankDisplayStore(path)

    assert store.get(_group()) == STORED_LIMIT
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT principal_kind, principal_id FROM group_rank_display_limits"
        ).fetchall() == [("qq_group", str(GROUP_ID))]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
