# SPDX-License-Identifier: MIT
# ruff: noqa: T201
"""Generate the Docker-bundled Git introduction timestamps for poke commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "ironsbot" / "_generated" / "poke_command_introductions.json"
BASELINE_COMMIT = "b97cb3ec"
ARCHIVE_COMMIT = "55a39fd12c8b562f8ac3eb8b95d5a71325e8981f"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in result.stdout.splitlines() if line]


def _command_ids() -> tuple[str, ...]:
    os.environ.setdefault("APP_CONFIG_PATH", str(ROOT / "config.example.toml"))
    from ironsbot.app.bootstrap import bootstrap

    application = bootstrap()
    return tuple(sorted(application.resources.commands.command_ids))


def _introduced_timestamps(
    command_ids: Iterable[str],
    revision: str | None = None,
) -> dict[str, str]:
    """Find all command introductions with one chronological Git history scan."""

    wanted = set(command_ids)
    if not wanted:
        return {}
    result = subprocess.run(
        [
            "git",
            "log",
            "--format=%H%x00%aI",
            "--reverse",
            "-p",
            "--no-ext-diff",
            "--unified=0",
            revision or f"{BASELINE_COMMIT}..HEAD",
            "--",
            "ironsbot",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    introduced: dict[str, str] = {}
    timestamp: str | None = None
    for line in result.stdout.splitlines():
        if "\x00" in line:
            _commit, timestamp = line.split("\x00", maxsplit=1)
            continue
        if timestamp is None or not line.startswith("+"):
            continue
        for command_id in wanted.difference(introduced):
            if f'"{command_id}"' in line:
                introduced[command_id] = timestamp
    return introduced


def _seed_commands(path: Path = MANIFEST_PATH) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        commands = payload.get("commands")
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(commands, dict):
        return {}
    return {
        command_id: introduced
        for command_id, introduced in commands.items()
        if isinstance(command_id, str) and isinstance(introduced, str)
    }


def _git_object_exists(revision: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def build_manifest(command_ids: Iterable[str]) -> dict[str, object]:
    _git_lines("merge-base", "--is-ancestor", BASELINE_COMMIT, "HEAD")
    ids = tuple(command_ids)
    commands = _introduced_timestamps(ids)
    if _git_object_exists(ARCHIVE_COMMIT):
        # The archived history is authoritative when it is available locally.
        archived = _introduced_timestamps(ids, ARCHIVE_COMMIT)
        baseline_time = _git_lines("show", "-s", "--format=%aI", BASELINE_COMMIT)[0]
        for command_id, introduced in archived.items():
            if datetime.fromisoformat(introduced) <= datetime.fromisoformat(
                baseline_time
            ):
                commands.pop(command_id, None)
            else:
                commands[command_id] = introduced
    else:
        # CI does not have access to the private history archive. Keep the reviewed,
        # checked-in pre-refactor results and combine them with current Git history.
        commands.update(
            {
                command_id: introduced
                for command_id, introduced in _seed_commands(MANIFEST_PATH).items()
                if command_id in ids
            }
        )
    return {
        "schema_version": 1,
        "baseline_commit": BASELINE_COMMIT,
        "archive_commit": ARCHIVE_COMMIT,
        "commands": commands,
    }


def main(*, output_path: Path = MANIFEST_PATH) -> None:
    manifest = build_manifest(_command_ids())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        display_path = output_path.relative_to(ROOT)
    except ValueError:
        display_path = output_path
    commands = manifest["commands"]
    assert isinstance(commands, dict)
    print(f"Generated {display_path}: {len(commands)} promoted commands")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--output", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    main(output_path=args.output)
