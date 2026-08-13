# SPDX-License-Identifier: MIT
"""Command-line adapter for offline IronsBot state migrations."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.platform_state_migration import (
    PlatformStateMigrationError,
    format_platform_state_migration_result,
    migrate_platform_state_identities,
)
from ironsbot.state_migration import (
    StateMigrationError,
    format_state_migration_result,
    migrate_state_databases,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


def main(argv: Iterable[str] | None = None) -> int:
    """Run the selected offline migration and print its report."""
    args = _parser().parse_args(None if argv is None else list(argv))
    if args.platform_identities:
        return _run_platform_identity_migration(args)
    try:
        result = migrate_state_databases(
            data_root=args.data_root,
            qq_state_path=args.qq_state,
            runtime_state_path=args.runtime_state,
            backup_root=args.backup_root,
            apply=args.apply,
        )
    except (OSError, sqlite3.Error, StateMigrationError) as error:
        sys.stderr.write(f"State migration failed: {error}\n")
        return 1
    sys.stdout.write(f"{format_state_migration_result(result)}\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consolidate legacy IronsBot state SQLite files.",
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--qq-state", type=Path)
    parser.add_argument("--runtime-state", type=Path)
    parser.add_argument("--ai-memory", type=Path)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument(
        "--platform-identities",
        action="store_true",
        help=(
            "Convert persisted OneBot integer identities to platform-neutral "
            "actor and conversation columns."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag only a dry run is performed.",
    )
    return parser


def _run_platform_identity_migration(args: argparse.Namespace) -> int:
    try:
        result = migrate_platform_state_identities(
            data_root=args.data_root,
            qq_state_path=args.qq_state,
            runtime_state_path=args.runtime_state,
            ai_memory_path=args.ai_memory,
            backup_root=args.backup_root,
            apply=args.apply,
        )
    except (OSError, sqlite3.Error, PlatformStateMigrationError) as error:
        sys.stderr.write(f"Platform identity migration failed: {error}\n")
        return 1
    sys.stdout.write(f"{format_platform_state_migration_result(result)}\n")
    return 0
