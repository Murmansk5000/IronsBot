# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts import generate_poke_command_introductions as generator

if TYPE_CHECKING:
    from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_generator_marks_sanctuary_command_after_baseline(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "poke-command-introductions.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_poke_command_introductions.py",
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        env={**os.environ, "APP_CONFIG_PATH": str(ROOT / "config.example.toml")},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert manifest["baseline_commit"] == "70e5d51824f29f8366c5a4efc2ed0b443b26e497"
    assert (
        manifest["commands"]["seer.autocard.sanctuary"] == "2026-08-11T17:32:19+08:00"
    )
    assert "help" not in manifest["commands"]


def test_first_use_dates_do_not_reintroduce_baseline_features() -> None:
    previous = {
        "help",
        "about",
        "rank.global_collection",
        "seer.player.query",
        "seer.pet.query",
        "seer.lucky_skin_window.query",
        "server_status.usage",
    }
    commands = generator.build_manifest(previous)["commands"]
    assert isinstance(commands, dict)
    assert not previous.intersection(commands)
    reviewed = generator._reviewed_introductions(generator.INTRODUCTIONS_PATH)
    if "seer.pet.flip" in reviewed:
        assert reviewed["seer.pet.flip"] == "2026-09-24T21:00:07+08:00"


def test_output_uses_only_registered_commands_without_mutating_reviewed_data(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    source = tmp_path / "reviewed.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "date_policy": "first_usable",
                "commands": {
                    "new.command": "2026-08-12T00:00:00+08:00",
                    "disabled.command": "2026-08-13T00:00:00+08:00",
                },
            }
        ),
        encoding="utf-8",
    )
    original = source.read_bytes()
    monkeypatch.setattr(generator, "INTRODUCTIONS_PATH", source)
    assert generator.build_manifest(("new.command", "help"))["commands"] == {
        "new.command": "2026-08-12T00:00:00+08:00"
    }
    assert source.read_bytes() == original


def test_metadata_generation_needs_no_private_archive_or_git_process(
    monkeypatch: MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail(
            "Reviewed first-use dates must not depend on Git object availability"
        )

    monkeypatch.setattr(subprocess, "run", forbidden)
    wanted = ("seer.autocard.sanctuary", "help", "seer.pet.query")
    assert generator.build_manifest(wanted)["commands"] == {
        "seer.autocard.sanctuary": "2026-08-11T17:32:19+08:00"
    }


@pytest.mark.parametrize(
    "commands",
    [{"bad": "2026-08-12T00:00:00"}, {"bad": 123}, {"": "2026-08-12T00:00:00+08:00"}],
)
def test_malformed_first_use_dates_fail_the_build(
    tmp_path: Path, commands: object
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "date_policy": "first_usable", "commands": commands}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        generator._reviewed_introductions(path)


def test_invalid_metadata_schema_is_not_silently_ignored(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        '{"schema_version":true,"commands":{},"date_policy":"first_usable"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        generator._reviewed_introductions(path)


def test_generated_file_cannot_overwrite_the_reviewed_source() -> None:
    with pytest.raises(ValueError, match="must not overwrite"):
        generator.main(output_path=generator.INTRODUCTIONS_PATH)
