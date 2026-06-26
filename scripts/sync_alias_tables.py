# SPDX-License-Identifier: MIT
# ruff: noqa: T201, TRY003
"""Sync alias CSV tables from upstream and local custom additions."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
TABLES_DIR = ROOT / "tables"
CUSTOM_TABLES_DIR = ROOT / "tables_custom"
PET_ALIASES_TABLE = "pet_aliases"
SUPPORTED_ALIAS_TABLES = {
    "pet_aliases",
    "mintmark_aliases",
    "mintmark_class_aliases",
}
UPSTREAM_PET_ALIASES_URL = (
    "https://raw.githubusercontent.com/Nattsu39/IronsBot/main/"
    "tables/pet_aliases.csv"
)


@dataclass(frozen=True, slots=True)
class AliasRow:
    name: str
    target_id: int


def _parse_alias_rows(text: str, *, source: str) -> list[AliasRow]:
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        return []

    missing = {"name", "target_id"} - set(reader.fieldnames)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"{source} missing required columns: {missing_text}")

    rows: list[AliasRow] = []
    for line_no, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        raw_target_id = (row.get("target_id") or "").strip()
        if not name and not raw_target_id:
            continue
        if not name or not raw_target_id:
            raise ValueError(f"{source}:{line_no} has incomplete alias row")
        try:
            target_id = int(raw_target_id)
        except ValueError as exc:
            raise ValueError(
                f"{source}:{line_no} target_id must be an integer"
            ) from exc
        rows.append(AliasRow(name=name, target_id=target_id))
    return rows


def _read_alias_rows(path: Path) -> list[AliasRow]:
    return _parse_alias_rows(path.read_text(encoding="utf-8-sig"), source=str(path))


def _fetch_upstream_pet_aliases() -> list[AliasRow]:
    request = Request(
        UPSTREAM_PET_ALIASES_URL,
        headers={"User-Agent": "IronsBot alias table sync"},
    )
    with urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8-sig")
    return _parse_alias_rows(text, source=UPSTREAM_PET_ALIASES_URL)


def _merge_rows(rows: list[AliasRow]) -> list[AliasRow]:
    seen: set[tuple[str, int]] = set()
    merged: list[AliasRow] = []
    for row in rows:
        key = (row.name, row.target_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _write_alias_rows(path: Path, rows: list[AliasRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(["name", "target_id"])
        writer.writerows((row.name, row.target_id) for row in rows)


def _custom_table_paths() -> list[Path]:
    if not CUSTOM_TABLES_DIR.exists():
        return []
    return sorted(CUSTOM_TABLES_DIR.glob("*.csv"))


def _load_base_rows(table_name: str, output_path: Path) -> list[AliasRow]:
    if table_name != PET_ALIASES_TABLE:
        return []
    try:
        base_rows = _fetch_upstream_pet_aliases()
        print(f"fetched upstream pet_aliases: {len(base_rows)} rows")
    except (OSError, TimeoutError, URLError) as exc:
        if not output_path.exists():
            raise
        print(
            "warning: failed to fetch upstream pet_aliases; "
            f"using existing {output_path}: {exc}",
            file=sys.stderr,
        )
        base_rows = _read_alias_rows(output_path)
    return base_rows


def _sync_alias_table(table_name: str) -> None:
    output_path = TABLES_DIR / f"{table_name}.csv"
    base_rows = _load_base_rows(table_name, output_path)

    custom_path = CUSTOM_TABLES_DIR / f"{table_name}.csv"
    custom_rows: list[AliasRow] = []
    if custom_path.exists():
        custom_rows = _read_alias_rows(custom_path)
        print(f"loaded custom {custom_path.name}: {len(custom_rows)} rows")

    merged_rows = _merge_rows([*base_rows, *custom_rows])
    _write_alias_rows(output_path, merged_rows)
    print(f"wrote {output_path}: {len(merged_rows)} rows")


def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    for path in _custom_table_paths():
        if path.stem not in SUPPORTED_ALIAS_TABLES:
            print(f"warning: ignoring unsupported custom alias table {path.name}")

    for table_name in sorted(SUPPORTED_ALIAS_TABLES):
        _sync_alias_table(table_name)


if __name__ == "__main__":
    main()
