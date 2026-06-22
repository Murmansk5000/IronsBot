# SPDX-License-Identifier: MIT
# ruff: noqa: T201, TRY003
"""Build alias SQLite database from CSV files under ``tables/``."""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLES_DIR = ROOT / "tables"
OUTPUT_DB = ROOT / "aliases-data.sqlite"
OUTPUT_SHA256 = ROOT / "aliases-data.sqlite.sha256"
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_table_name(name: str) -> str:
    if not TABLE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"invalid alias table name: {name}")
    return name


def _read_csv_rows(path: Path) -> list[tuple[str, int]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            return []
        missing = {"name", "target_id"} - set(reader.fieldnames)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"{path} missing required columns: {missing_text}")

        rows: list[tuple[str, int]] = []
        for line_no, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            raw_target_id = (row.get("target_id") or "").strip()
            if not name and not raw_target_id:
                continue
            if not name or not raw_target_id:
                raise ValueError(f"{path}:{line_no} has incomplete alias row")
            try:
                target_id = int(raw_target_id)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_no} target_id must be an integer"
                ) from exc
            rows.append((name, target_id))
    return rows


def _write_sha256(path: Path, output_path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    output_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def main() -> None:
    csv_files = sorted(TABLES_DIR.glob("*.csv"))
    if not csv_files:
        raise RuntimeError(f"no alias CSV files found in {TABLES_DIR}")

    OUTPUT_DB.unlink(missing_ok=True)
    OUTPUT_SHA256.unlink(missing_ok=True)

    conn = sqlite3.connect(OUTPUT_DB)
    try:
        for csv_file in csv_files:
            table_name = _validate_table_name(csv_file.stem)
            rows = _read_csv_rows(csv_file)

            conn.execute(
                f"CREATE TABLE [{table_name}] "
                "(name TEXT NOT NULL, target_id INTEGER NOT NULL, "
                "PRIMARY KEY (name, target_id))"
            )
            conn.executemany(
                f"INSERT INTO [{table_name}] (name, target_id) VALUES (?, ?)",
                rows,
            )
            print(f"{csv_file.name} -> {table_name}: {len(rows)} rows")
        conn.commit()
    finally:
        conn.close()

    _write_sha256(OUTPUT_DB, OUTPUT_SHA256)
    size_kb = OUTPUT_DB.stat().st_size / 1024
    print(f"\nGenerated {OUTPUT_DB} ({size_kb:.1f} KB)")
    print(f"Generated {OUTPUT_SHA256}")


if __name__ == "__main__":
    main()
