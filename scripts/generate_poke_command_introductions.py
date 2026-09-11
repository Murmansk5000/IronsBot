# SPDX-License-Identifier: MIT
# ruff: noqa: T201
"""Generate the Docker-bundled Git introduction timestamps for poke commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "ironsbot" / "_generated" / "poke_command_introductions.json"
BASELINE_COMMIT = "f53f7dae"

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


def _introduced_at(command_id: str) -> str | None:
    lines = _git_lines(
        "log",
        "--format=%aI",
        "--reverse",
        "-S",
        f'"{command_id}"',
        f"{BASELINE_COMMIT}..HEAD",
        "--",
        "ironsbot",
    )
    return lines[0] if lines else None


def build_manifest(command_ids: Iterable[str]) -> dict[str, object]:
    _git_lines("merge-base", "--is-ancestor", BASELINE_COMMIT, "HEAD")
    commands = {
        command_id: timestamp
        for command_id in sorted(set(command_ids))
        if (timestamp := _introduced_at(command_id)) is not None
    }
    return {
        "schema_version": 1,
        "baseline_commit": BASELINE_COMMIT,
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
    print(
        f"Generated {display_path}: "
        f"{len(commands)} promoted commands"
    )


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--output", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    main(output_path=args.output)
