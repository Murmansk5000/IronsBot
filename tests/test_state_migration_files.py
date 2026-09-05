from pathlib import Path

import pytest

import ironsbot.state_migration_files as files
from ironsbot.state_migration_files import (
    SqliteBundleChange,
    SqliteBundleInstallError,
    apply_sqlite_bundle_changes,
    copy_sqlite_bundle,
)

SUFFIXES = ("", "-wal", "-shm", "-journal")


def _original(tmp_path: Path, name: str) -> tuple[Path, Path]:
    target = tmp_path / name
    backup = tmp_path / "backup" / name
    for suffix in SUFFIXES:
        Path(f"{target}{suffix}").write_bytes(f"original-{name}{suffix}".encode())
    copy_sqlite_bundle(target, backup)
    return target, backup


def _assert_restored(target: Path, backup: Path) -> None:
    for suffix in SUFFIXES:
        assert Path(f"{target}{suffix}").read_bytes() == Path(
            f"{backup}{suffix}"
        ).read_bytes()


def test_replace_removes_old_sidecars_and_keeps_backup(tmp_path: Path) -> None:
    target, backup = _original(tmp_path, "state.sqlite")
    replacement = tmp_path / "new.sqlite"
    replacement.write_bytes(b"new")

    apply_sqlite_bundle_changes((SqliteBundleChange(target, replacement, backup),))

    assert target.read_bytes() == b"new"
    assert not replacement.exists()
    for suffix in SUFFIXES[1:]:
        assert not Path(f"{target}{suffix}").exists()
        assert Path(f"{backup}{suffix}").is_file()


@pytest.mark.parametrize("failure", [PermissionError, KeyboardInterrupt])
def test_second_replace_failure_restores_all_originals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException],
) -> None:
    first, backup_first = _original(tmp_path, "first.sqlite")
    second, backup_second = _original(tmp_path, "second.sqlite")
    first_new, second_new = tmp_path / "first-new", tmp_path / "second-new"
    first_new.write_bytes(b"new-first")
    second_new.write_bytes(b"new-second")
    original_replace = Path.replace

    def fail_second(path: Path, target: Path) -> Path:
        if path == second_new:
            raise failure
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second)
    with pytest.raises(failure):
        apply_sqlite_bundle_changes((
            SqliteBundleChange(first, first_new, backup_first),
            SqliteBundleChange(second, second_new, backup_second),
        ))

    _assert_restored(first, backup_first)
    _assert_restored(second, backup_second)


def test_sidecar_cleanup_failure_restores_partly_modified_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, backup = _original(tmp_path, "state.sqlite")
    replacement = tmp_path / "new.sqlite"
    replacement.write_bytes(b"new")
    original_unlink = Path.unlink
    failed = False

    def fail_shm(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal failed
        if path == Path(f"{target}-shm") and not failed:
            failed = True
            raise PermissionError
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_shm)
    with pytest.raises(PermissionError):
        apply_sqlite_bundle_changes((SqliteBundleChange(target, replacement, backup),))

    _assert_restored(target, backup)


def test_failed_rollback_continues_other_restores_and_reports_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, backup_first = _original(tmp_path, "first.sqlite")
    second, backup_second = _original(tmp_path, "second.sqlite")
    first_new = tmp_path / "new"
    first_new.write_bytes(b"new")
    original_unlink = Path.unlink
    original_copy = files.copy_sqlite_bundle

    def fail_delete(path: Path, *, missing_ok: bool = False) -> None:
        if path == second:
            raise PermissionError
        original_unlink(path, missing_ok=missing_ok)

    def fail_restore(source: Path, target: Path) -> None:
        if source == backup_second:
            raise PermissionError
        original_copy(source, target)

    monkeypatch.setattr(Path, "unlink", fail_delete)
    monkeypatch.setattr(files, "copy_sqlite_bundle", fail_restore)
    with pytest.raises(SqliteBundleInstallError, match="rollback incomplete") as caught:
        apply_sqlite_bundle_changes((
            SqliteBundleChange(first, first_new, backup_first),
            SqliteBundleChange(second, backup=backup_second),
        ))

    _assert_restored(first, backup_first)
    assert str(second) in str(caught.value)
    assert str(backup_second) in str(caught.value)
    assert isinstance(caught.value.__cause__, PermissionError)
    for suffix in SUFFIXES:
        assert Path(f"{backup_second}{suffix}").is_file()


@pytest.mark.parametrize("invalid", ["no_backup", "duplicate", "overlap", "orphan"])
def test_invalid_plan_never_modifies_files(tmp_path: Path, invalid: str) -> None:
    target, backup = _original(tmp_path, "state.sqlite")
    replacement = tmp_path / "new"
    replacement.write_bytes(b"new")
    change = SqliteBundleChange(target, replacement, backup)
    if invalid == "no_backup":
        changes = (SqliteBundleChange(target, replacement),)
    elif invalid == "duplicate":
        changes = (change, change)
    elif invalid == "overlap":
        changes = (SqliteBundleChange(target, target, backup),)
    else:
        orphan = tmp_path / "orphan"
        Path(f"{orphan}-wal").write_bytes(b"orphan")
        changes = (change, SqliteBundleChange(orphan))

    with pytest.raises(SqliteBundleInstallError):
        apply_sqlite_bundle_changes(changes)

    _assert_restored(target, backup)
    assert replacement.read_bytes() == b"new"
