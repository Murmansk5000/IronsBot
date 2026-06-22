# SPDX-License-Identifier: MIT
import sqlite3
from pathlib import Path

from pytest import MonkeyPatch

from scripts import build_alias_db, sync_alias_tables


def test_sync_alias_tables_merges_supported_custom_tables(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    tables_dir = tmp_path / "tables"
    custom_dir = tmp_path / "tables_custom"
    custom_dir.mkdir()
    (custom_dir / "pet_aliases.csv").write_text(
        "name,target_id\nio,3437\nio,4911\n",
        encoding="utf-8",
    )
    (custom_dir / "mintmark_aliases.csv").write_text(
        "name,target_id\n毛毛,45026\n",
        encoding="utf-8",
    )
    (custom_dir / "mintmark_class_aliases.csv").write_text(
        "name,target_id\nk16,89\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sync_alias_tables, "TABLES_DIR", tables_dir)
    monkeypatch.setattr(sync_alias_tables, "CUSTOM_TABLES_DIR", custom_dir)
    monkeypatch.setattr(
        sync_alias_tables,
        "_fetch_upstream_pet_aliases",
        lambda: [sync_alias_tables.AliasRow(name="虫母", target_id=4866)],
    )

    sync_alias_tables.main()

    assert (tables_dir / "pet_aliases.csv").read_text(encoding="utf-8") == (
        "name,target_id\n虫母,4866\nio,3437\nio,4911\n"
    )
    assert (tables_dir / "mintmark_aliases.csv").read_text(
        encoding="utf-8"
    ) == "name,target_id\n毛毛,45026\n"
    assert (tables_dir / "mintmark_class_aliases.csv").read_text(
        encoding="utf-8"
    ) == "name,target_id\nk16,89\n"


def test_sync_alias_tables_does_not_keep_old_non_pet_alias_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    tables_dir = tmp_path / "tables"
    custom_dir = tmp_path / "tables_custom"
    tables_dir.mkdir()
    custom_dir.mkdir()
    (tables_dir / "mintmark_class_aliases.csv").write_text(
        "name,target_id\n沧吟星海,75\nk14,75\n",
        encoding="utf-8",
    )
    (custom_dir / "mintmark_class_aliases.csv").write_text(
        "name,target_id\nk14,75\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sync_alias_tables, "TABLES_DIR", tables_dir)
    monkeypatch.setattr(sync_alias_tables, "CUSTOM_TABLES_DIR", custom_dir)
    monkeypatch.setattr(sync_alias_tables, "_fetch_upstream_pet_aliases", list)

    sync_alias_tables.main()

    assert (tables_dir / "mintmark_class_aliases.csv").read_text(
        encoding="utf-8"
    ) == "name,target_id\nk14,75\n"


def test_build_alias_db_builds_all_alias_tables(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    (tables_dir / "pet_aliases.csv").write_text(
        "name,target_id\nio,3437\n",
        encoding="utf-8",
    )
    (tables_dir / "mintmark_aliases.csv").write_text(
        "name,target_id\n毛毛,45026\n",
        encoding="utf-8",
    )
    (tables_dir / "mintmark_class_aliases.csv").write_text(
        "name,target_id\nk16,89\n",
        encoding="utf-8",
    )
    output_db = tmp_path / "aliases-data.sqlite"
    output_sha256 = tmp_path / "aliases-data.sqlite.sha256"
    monkeypatch.setattr(build_alias_db, "TABLES_DIR", tables_dir)
    monkeypatch.setattr(build_alias_db, "OUTPUT_DB", output_db)
    monkeypatch.setattr(build_alias_db, "OUTPUT_SHA256", output_sha256)

    build_alias_db.main()

    conn = sqlite3.connect(output_db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }
        assert tables == {
            "pet_aliases",
            "mintmark_aliases",
            "mintmark_class_aliases",
        }
        assert conn.execute("select * from pet_aliases").fetchall() == [("io", 3437)]
        assert conn.execute("select * from mintmark_aliases").fetchall() == [
            ("毛毛", 45026)
        ]
        assert conn.execute("select * from mintmark_class_aliases").fetchall() == [
            ("k16", 89)
        ]
    finally:
        conn.close()
    assert output_sha256.exists()
