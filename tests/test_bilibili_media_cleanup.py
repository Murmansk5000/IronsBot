from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pytest

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.integrations.storage import bilibili_delivery_ledger as storage
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    RETENTION_SECONDS,
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.delivery_ledger import MediaCleanupResult
from ironsbot.services.bilibili.delivery_recovery import BiliDeliveryRecovery
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.test_bilibili_outbound_delivery import _item
from tests.test_bilibili_unit_retries import TARGET

if TYPE_CHECKING:
    from pathlib import Path

NOW = 2_000_000.0
HOUR = 3600


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(now=NOW)
    monkeypatch.setattr(storage, "time", SimpleNamespace(time=lambda: state.now))
    state.ledger = SqliteDynamicDeliveryLedger(tmp_path / "delivery.sqlite")
    return state


def prepare(state: SimpleNamespace, key: str, *, age: float = 0) -> None:
    item = _item()
    item["id_str"] = key
    state.ledger.prepare(
        item, int(state.now - age), 123, BiliPushTargets([], [], [], []), ()
    )
    with SqliteDatabase(state.ledger.path).connect() as db:
        db.execute("UPDATE deliveries SET created=? WHERE id=?", (state.now - age, key))


def media(ledger: SqliteDynamicDeliveryLedger, key: str, data: bytes) -> Path:
    message = OutboundMessage((BinaryImagePart(data, "image/png", "image.png"),))
    ledger.freeze_media(key, message)
    return ledger.media_root / hashlib.sha256(data).hexdigest()


def aged(path: Path, seconds: float = HOUR) -> None:
    os.utime(path, (NOW - seconds, NOW - seconds))


def test_expiry_boundary_and_no_renewal(state: SimpleNamespace) -> None:
    prepare(state, "one")
    path = media(state.ledger, "one", b"original")
    aged(path)
    state.now += RETENTION_SECONDS - 1
    assert state.ledger.cleanup_media().deleted_files == 0
    state.ledger.load_media("one")
    state.now += 1
    assert state.ledger.cleanup_media().deleted_files == 0
    state.now += 1
    assert state.ledger.cleanup_media().deleted_files == 1
    assert not path.exists()
    assert state.ledger.cleanup_media().deleted_files == 0
    with SqliteDatabase(state.ledger.path).connect() as db:
        assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM media_manifests").fetchone()[0] == 1


@pytest.mark.parametrize("snapshot", ["media", "text", "unit"])
def test_shared_digest_protects_every_snapshot_kind(
    state: SimpleNamespace,
    snapshot: str,
) -> None:
    prepare(state, "old", age=RETENTION_SECONDS + 1)
    prepare(state, "current")
    path = media(state.ledger, "old", b"shared")
    message = OutboundMessage((BinaryImagePart(b"shared", "image/png", "one.png"),))
    if snapshot == "media":
        state.ledger.freeze_media("current", message)
    elif snapshot == "text":
        state.ledger.freeze_text("current", message)
    else:
        state.ledger.freeze_unit("current", TARGET, "image:1", message)
    aged(path)
    assert state.ledger.cleanup_media().deleted_files == 0
    assert path.read_bytes() == b"shared"
    state.now += RETENTION_SECONDS + 1
    assert state.ledger.cleanup_media().deleted_files == 1


def test_publication_time_limits_retention(state: SimpleNamespace) -> None:
    prepare(state, "one")
    path = media(state.ledger, "one", b"old publication")
    aged(path)
    with SqliteDatabase(state.ledger.path).connect() as db:
        db.execute(
            "UPDATE deliveries SET payload=json_set(payload,'$.pub_ts',?)",
            (NOW - RETENTION_SECONDS - 1,),
        )
    assert state.ledger.cleanup_media().deleted_files == 1


def test_sending_across_expiry_preserves_receipts_and_budget(
    state: SimpleNamespace,
) -> None:
    prepare(state, "one", age=RETENTION_SECONDS + 1)
    path = media(state.ledger, "one", b"inflight")
    aged(path)
    with SqliteDatabase(state.ledger.path).connect() as db:
        db.execute(
            "INSERT INTO stages(dynamic_id,target,stage,state,attempts) "
            "VALUES ('one','target','image:1','sending',2)"
        )
        before = db.execute("SELECT * FROM stages").fetchall()
    assert state.ledger.cleanup_media().deleted_files == 0
    with SqliteDatabase(state.ledger.path).connect() as db:
        assert db.execute("SELECT * FROM stages").fetchall() == before
        db.execute("UPDATE stages SET state='success',result='receipt'")
    assert state.ledger.cleanup_media().deleted_files == 1
    with SqliteDatabase(state.ledger.path).connect() as db:
        assert db.execute("SELECT state,result,attempts FROM stages").fetchone() == (
            "success",
            "receipt",
            2,
        )


def test_orphan_grace_temp_files_and_unknown_names(state: SimpleNamespace) -> None:
    root = state.ledger.media_root
    root.mkdir()
    old = root / hashlib.sha256(b"orphan").hexdigest()
    old.write_bytes(b"orphan")
    temporary = root / ".media-abc123_4"
    temporary.write_bytes(b"temp")
    recent = root / hashlib.sha256(b"recent").hexdigest()
    recent.write_bytes(b"recent")
    unknown = root / "user-photo.png"
    unknown.write_bytes(b"not ours")
    unknown_temp = root / ".media-user-backup"
    unknown_temp.write_bytes(b"not a generated temporary")
    directory = root / ".media-directory"
    directory.mkdir()
    for path in (old, temporary, unknown, unknown_temp):
        aged(path)
    aged(recent, HOUR - 1)
    result = state.ledger.cleanup_media()
    assert result.deleted_files == len((old, temporary))
    assert result.deleted_bytes == len(b"orphantemp")
    assert recent.exists() and unknown.exists() and directory.exists()
    assert unknown_temp.exists()
    state.now += 1
    assert state.ledger.cleanup_media().deleted_files == 1


@pytest.mark.parametrize(
    "table,payload",
    [
        ("media_manifests", '{"invalid":true}'),
        ("text_manifests", '[{"media":7}]'),
        ("unit_messages", '["invalid"]'),
        ("media_manifests", '[{"sha256":"' + "a" * 64 + '"}]'),
        ("text_manifests", '[{"actor":null}]'),
    ],
)
def test_corrupt_manifest_aborts_before_any_delete(
    state: SimpleNamespace,
    table: str,
    payload: str,
) -> None:
    prepare(state, "one", age=RETENTION_SECONDS + 1)
    path = media(state.ledger, "one", b"protect on corruption")
    aged(path)
    with SqliteDatabase(state.ledger.path).connect() as db:
        if table == "unit_messages":
            db.execute(
                "INSERT INTO unit_messages VALUES ('one','target','image:1',?)",
                (payload,),
            )
        else:
            db.execute(f"INSERT OR REPLACE INTO {table} VALUES ('one',?)", (payload,))
    result = state.ledger.cleanup_media()
    assert result.errors == 1 and result.deleted_files == 0
    assert result.reason == "invalid_manifest"
    assert path.exists()


def test_delete_failure_does_not_stop_other_files(
    state: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare(state, "one", age=RETENTION_SECONDS + 1)
    prepare(state, "two", age=RETENTION_SECONDS + 1)
    failed = media(state.ledger, "one", b"denied")
    removed = media(state.ledger, "two", b"removed")
    aged(failed)
    aged(removed)
    unlink = type(failed).unlink

    def deny_one(path: Path, **kwargs: Any) -> None:
        if str(path) == str(failed):
            raise PermissionError
        unlink(path, **kwargs)

    monkeypatch.setattr("pathlib.Path.unlink", deny_one)
    result = state.ledger.cleanup_media()
    assert result.errors == 1 and result.deleted_files == 1
    assert failed.exists() and not removed.exists()


@pytest.mark.parametrize("root_link", [False, True])
def test_links_are_never_followed(
    tmp_path: Path,
    state: SimpleNamespace,
    *,
    root_link: bool,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / hashlib.sha256(b"outside").hexdigest()
    original.write_bytes(b"outside")
    aged(original)
    root = state.ledger.media_root
    try:
        if root_link:
            root.symlink_to(outside, target_is_directory=True)
        else:
            root.mkdir()
            (root / original.name).symlink_to(original)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    result = state.ledger.cleanup_media()
    assert result.deleted_files == 0 and original.exists()


@pytest.mark.parametrize("snapshot", ["media", "text", "unit"])
def test_freeze_holds_writer_lock_before_writing_bytes(
    state: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: str,
) -> None:
    prepare(state, "one")
    encode = storage.encode_media if snapshot == "media" else storage.freeze_message

    def guarded(message: OutboundMessage | None, root: Path) -> Any:
        assert message is not None
        with SqliteDatabase(state.ledger.path).connect() as db:
            db.execute("PRAGMA busy_timeout=0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                db.execute("BEGIN IMMEDIATE")
        return encode(message, root)

    monkeypatch.setattr(
        storage, "encode_media" if snapshot == "media" else "freeze_message", guarded
    )
    message = OutboundMessage((BinaryImagePart(b"guarded", "image/png", "one.png"),))
    if snapshot == "media":
        state.ledger.freeze_media("one", message)
    elif snapshot == "text":
        state.ledger.freeze_text("one", message)
    else:
        state.ledger.freeze_unit("one", TARGET, "image:1", message)


def test_concurrent_freeze_and_cleanup_keep_new_reference(
    state: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare(state, "one")
    written = threading.Event()
    release = threading.Event()
    started = threading.Event()
    encode = storage.encode_media

    def pause_after_bytes(message: OutboundMessage | None, root: Path) -> str:
        payload = encode(message, root)
        for path in root.iterdir():
            aged(path)
        written.set()
        assert release.wait(5)
        return payload

    monkeypatch.setattr(storage, "encode_media", pause_after_bytes)

    def collect() -> MediaCleanupResult:
        started.set()
        return state.ledger.cleanup_media()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(media, state.ledger, "one", b"race")
        assert written.wait(5)
        collector = pool.submit(collect)
        assert started.wait(5)
        release.set()
        path = writer.result(timeout=5)
        assert collector.result(timeout=5).deleted_files == 0
    assert path.read_bytes() == b"race"


@pytest.mark.asyncio
async def test_cleanup_runs_hourly_without_blocking_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(
        "ironsbot.services.bilibili.delivery_recovery.time",
        SimpleNamespace(monotonic=lambda: clock.now),
    )
    ledger = Mock()
    ledger.pending.return_value = []
    ledger.cleanup_media.return_value = MediaCleanupResult()
    recovery = BiliDeliveryRecovery(
        cast("Any", Mock(ledger=ledger)), cast("Any", Mock())
    )
    await recovery()
    await recovery("bot-a")
    await recovery("bot-b")
    ledger.cleanup_media.assert_called_once()
    clock.now += HOUR
    ledger.cleanup_media.side_effect = OSError("private signed URL")
    await recovery("scan")
    assert ledger.pending.call_count == len(("startup", "bot-a", "bot-b", "scan"))


@pytest.mark.asyncio
async def test_cleanup_file_work_runs_off_loop() -> None:
    entered = threading.Event()
    release = threading.Event()
    ledger = Mock()
    ledger.pending.return_value = []

    def slow_cleanup() -> MediaCleanupResult:
        entered.set()
        assert release.wait(5)
        return MediaCleanupResult()

    ledger.cleanup_media.side_effect = slow_cleanup
    recovery = BiliDeliveryRecovery(
        cast("Any", Mock(ledger=ledger)), cast("Any", Mock())
    )
    task = asyncio.create_task(recovery())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_cancel_waits_for_cleanup_worker_to_finish() -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    ledger = Mock()
    ledger.pending.return_value = []

    def slow_cleanup() -> MediaCleanupResult:
        entered.set()
        assert release.wait(5)
        finished.set()
        return MediaCleanupResult()

    ledger.cleanup_media.side_effect = slow_cleanup
    recovery = BiliDeliveryRecovery(
        cast("Any", Mock(ledger=ledger)), cast("Any", Mock())
    )
    task = asyncio.create_task(recovery())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    ledger.pending.assert_not_called()


def test_restart_preserves_fresh_references(state: SimpleNamespace) -> None:
    prepare(state, "one")
    path = media(state.ledger, "one", b"restart")
    aged(path)
    reopened = SqliteDynamicDeliveryLedger(state.ledger.path)
    reopened.recover()
    assert reopened.cleanup_media().deleted_files == 0
    assert reopened.load_media("one")[0]
    state.now += RETENTION_SECONDS + 1
    assert reopened.cleanup_media().deleted_files == 1
