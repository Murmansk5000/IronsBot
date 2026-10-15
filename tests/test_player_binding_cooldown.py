# SPDX-License-Identifier: MIT
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.platform import ActorPrincipal, ActorRef, Platform
from ironsbot.integrations.storage.platform_state_platform_copy import (
    copy_platform_player_bindings,
)
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.services.seer.player_binding import PlayerBindingError
from ironsbot.services.seer.player_service import PendingPlayerQuery, PlayerService

START = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
PLAYER_A = 123456
PLAYER_B = 654321


def _actor(platform: Platform = Platform.ONEBOT) -> ActorRef:
    return ActorRef(platform, "10001", account_id="test-app")


def _service(store: SqlitePlayerBindingStore, now: datetime) -> PlayerService:
    return PlayerService(
        config=SeerConfig(),
        bindings=store,
        headless=cast("Any", None),
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: now,
    )


def _pending(player: int) -> PendingPlayerQuery:
    return PendingPlayerQuery(
        player_id=player,
        user_info=SimpleNamespace(nick="sample"),
        more_info=object(),
        player_message="profile",
        section_plan=cast("Any", object()),
    )


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_restore_same_player_and_switch_after_deadline(
    tmp_path: Path,
    platform: Platform,
) -> None:
    actor = _actor(platform)
    store = SqlitePlayerBindingStore(tmp_path / "state.sqlite")
    initial = _service(store, START)
    assert initial.bind_shortcut_target(actor, PLAYER_A).startswith("已设置")
    later = _service(store, START + timedelta(hours=1))
    assert later.unbind(actor) == "已解除默认米米号。"
    assert later.unbind(actor) == "当前没有已绑定的米米号。"
    assert "换绑未成功" in later.bind_shortcut_target(actor, PLAYER_B)
    assert later.bind_shortcut_target(actor, PLAYER_A).startswith("已设置")
    assert store.get(actor).last_changed_at == START
    assert later.unbind(actor).startswith("已解除")
    assert later.save_binding_choice(
        actor, _pending(PLAYER_A), accepted=True
    ).startswith("已设置")
    assert store.get(actor).last_changed_at == START
    assert "换绑未成功" in later.save_binding_choice(
        actor,
        _pending(PLAYER_B),
        accepted=True,
        replacing_existing=True,
    )
    deadline = datetime(2026, 10, 12, 16, tzinfo=timezone.utc)
    due = _service(store, deadline)
    assert due.save_binding_choice(
        actor,
        _pending(PLAYER_B),
        accepted=True,
        replacing_existing=True,
    ).startswith("已设置")
    state = SqlitePlayerBindingStore(tmp_path / "state.sqlite").get(actor)
    assert state.player_id == state.last_bound_player_id == PLAYER_B
    assert state.last_changed_at == deadline
    due.unbind(actor)
    assert "换绑未成功" in due.bind_shortcut_target(actor, PLAYER_A)


def test_decline_and_zero_cooldown_do_not_retime_same_player(tmp_path: Path) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "state.sqlite")
    actor = _actor()
    store.bind(actor=actor, player_id=PLAYER_A, player_nick="a", changed_at=START)
    store.unbind(actor=actor, changed_at=START + timedelta(hours=1))
    store.decline(actor=actor)
    assert store.get(actor).last_changed_at == START
    store.bind(
        actor=actor,
        player_id=PLAYER_A,
        player_nick="a",
        changed_at=START + timedelta(hours=2),
    )
    assert store.get(actor).last_changed_at == START
    store.bind(
        actor=actor,
        player_id=PLAYER_B,
        player_nick="b",
        changed_at=START + timedelta(hours=3),
        cooldown_days=0,
    )
    assert store.get(actor).last_changed_at == START + timedelta(hours=3)


def test_parallel_first_bindings_only_one_wins(tmp_path: Path) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "state.sqlite")
    store.get(_actor())
    barrier = Barrier(2)

    def bind(player: int) -> str:
        barrier.wait()
        try:
            store.bind(
                actor=_actor(),
                player_id=player,
                player_nick="sample",
                changed_at=START,
                cooldown_days=3,
            )
        except PlayerBindingError:
            return "rejected"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(bind, (PLAYER_A, PLAYER_B)))
    assert sorted(results) == ["rejected", "saved"]
    assert store.get(_actor()).last_bound_player_id == store.get(_actor()).player_id


def test_atomic_first_choice_cannot_overwrite_an_intervening_binding(
    tmp_path: Path,
) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "state.sqlite")
    store.bind(actor=_actor(), player_id=PLAYER_A, player_nick="a", changed_at=START)
    with pytest.raises(PlayerBindingError, match="当前绑定已变化"):
        store.bind(
            actor=_actor(),
            player_id=PLAYER_B,
            player_nick="b",
            changed_at=START + timedelta(days=4),
            only_if_unbound=True,
        )
    assert store.get(_actor()).player_id == PLAYER_A


def test_explicit_binding_rejects_switch_after_unbind_before_query(
    tmp_path: Path,
) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "state.sqlite")
    store.bind(actor=_actor(), player_id=PLAYER_A, player_nick="a", changed_at=START)
    store.unbind(actor=_actor())
    service = _service(store, START + timedelta(hours=1))
    service.query = AsyncMock()
    result = asyncio.run(service.bind_player(PLAYER_B, actor=_actor()))
    assert "换绑未成功" in result.message
    assert "当前未绑定" in result.message
    service.query.assert_not_awaited()


def test_legacy_migration_preserves_bound_history_and_clears_unbound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE ironsbot_schema_migrations (
                namespace TEXT PRIMARY KEY, version INTEGER, updated_at TEXT);
            INSERT INTO ironsbot_schema_migrations VALUES ('player_bindings', 3, 'old');
            CREATE TABLE player_bindings (
                principal_kind TEXT, principal_id TEXT, player_id INTEGER,
                player_nick TEXT, choice_completed INTEGER, last_changed_at TEXT,
                created_at TEXT, updated_at TEXT,
                PRIMARY KEY(principal_kind, principal_id));
        """)
        conn.executemany(
            "INSERT INTO player_bindings VALUES ('qq', ?, ?, '', 1, ?, 'old', 'old')",
            [
                ("10001", PLAYER_A, START.isoformat()),
                ("10002", None, START.isoformat()),
                ("10003", PLAYER_B, None),
            ],
        )
    store = SqlitePlayerBindingStore(path)
    bound = store.get(_actor())
    assert bound.last_bound_player_id == PLAYER_A
    assert bound.last_changed_at == START
    missing = store.get(ActorRef(Platform.ONEBOT, "10003"))
    assert missing.last_bound_player_id == PLAYER_B
    assert missing.last_changed_at is None
    unbound = ActorRef(Platform.ONEBOT, "10002")
    assert store.get(unbound).last_changed_at is None
    assert store.get(unbound).last_bound_player_id is None
    assert (
        _service(store, START)
        .bind_shortcut_target(unbound, PLAYER_B)
        .startswith("已设置")
    )


def test_merge_unbound_histories_keeps_complete_newer_pair(tmp_path: Path) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "state.sqlite")
    source = ActorRef(Platform.ONEBOT, "10001")
    target = ActorRef(Platform.ONEBOT, "10002")
    for actor, player, date in (
        (source, PLAYER_A, START),
        (target, PLAYER_B, START - timedelta(days=1)),
    ):
        store.bind(actor=actor, player_id=player, player_nick="sample", changed_at=date)
        store.unbind(actor=actor)
    store.merge_principals(
        ActorPrincipal("qq", source.id), ActorPrincipal("qq", target.id)
    )
    state = store.get(target)
    assert state.player_id is None
    assert state.last_bound_player_id == PLAYER_A
    assert state.last_changed_at == START
    assert store.get(source).last_bound_player_id is None


def test_trusted_cross_platform_identity_shares_cooldown(tmp_path: Path) -> None:
    store = SqlitePlayerBindingStore(
        tmp_path / "state.sqlite",
        principal_for=lambda _actor: ActorPrincipal("qq", "10001"),
    )
    onebot = _actor()
    official = _actor(Platform.QQ_OFFICIAL)
    service = _service(store, START)
    service.bind_shortcut_target(onebot, PLAYER_A)
    service.unbind(official)
    assert "换绑未成功" in service.bind_shortcut_target(official, PLAYER_B)
    assert service.bind_shortcut_target(official, PLAYER_A).startswith("已设置")
    assert store.get(onebot).player_id == PLAYER_A


def test_offline_copy_preserves_new_unbound_history(tmp_path: Path) -> None:
    source_path = tmp_path / "source.sqlite"
    target_path = tmp_path / "target.sqlite"
    source_store = SqlitePlayerBindingStore(source_path)
    source_store.bind(
        actor=_actor(), player_id=PLAYER_A, player_nick="a", changed_at=START
    )
    source_store.unbind(actor=_actor())
    target_store = SqlitePlayerBindingStore(target_path)
    target_store.get(_actor())
    with sqlite3.connect(source_path) as source, sqlite3.connect(target_path) as target:
        source.row_factory = sqlite3.Row
        copy_platform_player_bindings(source, target, qq_official_account_id=None)
    state = target_store.get(_actor())
    assert state.player_id is None
    assert state.last_bound_player_id == PLAYER_A
    assert state.last_changed_at == START


def test_failed_write_rolls_back_cooldown_and_current_binding(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = SqlitePlayerBindingStore(path)
    store.bind(actor=_actor(), player_id=PLAYER_A, player_nick="a", changed_at=START)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TRIGGER reject_binding BEFORE UPDATE ON player_bindings
            BEGIN SELECT RAISE(ABORT, 'test write failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="test write failure"):
        store.bind(
            actor=_actor(),
            player_id=PLAYER_B,
            player_nick="b",
            changed_at=START + timedelta(days=4),
            cooldown_days=3,
        )
    assert store.get(_actor()).player_id == PLAYER_A
    assert store.get(_actor()).last_changed_at == START
