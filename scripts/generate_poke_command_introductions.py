# SPDX-License-Identifier: MIT
# ruff: noqa: T201
"""Bundle reviewed first-use dates; refactors and local Git objects are irrelevant."""

from __future__ import annotations

import json
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent
INTRODUCTIONS_PATH = ROOT / "docs" / "command-first-use.json"
MANIFEST_PATH = ROOT / "ironsbot" / "_generated" / "poke_command_introductions.json"
BASELINE_COMMIT = "70e5d51824f29f8366c5a4efc2ed0b443b26e497"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _command_ids() -> tuple[str, ...]:
    os.environ.setdefault("APP_CONFIG_PATH", str(ROOT / "config.example.toml"))
    from ironsbot.app.bootstrap import bootstrap

    application = bootstrap()
    return tuple(sorted(application.resources.commands.command_ids))


def _reviewed_introductions(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "date_policy", "commands"}
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or payload.get("date_policy") != "first_usable"
        or not isinstance(payload.get("commands"), dict)
    ):
        message = "Invalid reviewed command first-use metadata"
        raise ValueError(message)
    commands: dict[str, str] = {}
    for command_id, value in payload["commands"].items():
        if (
            not isinstance(command_id, str)
            or not command_id
            or not isinstance(value, str)
        ):
            message = "Invalid command first-use entry"
            raise ValueError(message)
        if datetime.fromisoformat(value).tzinfo is None:
            message = "Command first-use timestamps require a timezone"
            raise ValueError(message)
        commands[command_id] = value
    return commands


def build_manifest(command_ids: Iterable[str]) -> dict[str, object]:
    wanted = set(command_ids)
    commands = {
        command_id: introduced
        for command_id, introduced in _reviewed_introductions(
            INTRODUCTIONS_PATH
        ).items()
        if command_id in wanted
    }
    return {
        "schema_version": 1,
        "baseline_commit": BASELINE_COMMIT,
        "commands": commands,
    }


def main(*, output_path: Path = MANIFEST_PATH) -> None:
    if output_path.resolve() == INTRODUCTIONS_PATH.resolve():
        message = "Generated output must not overwrite reviewed first-use data"
        raise ValueError(message)
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
