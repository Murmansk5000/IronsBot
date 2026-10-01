# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

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
    assert manifest["baseline_commit"] == "c83f48e8dd65ba71dd4227c8251083b9443ded4b"
    assert "seer.autocard.sanctuary" in manifest["commands"]
    assert "help" not in manifest["commands"]


def test_manifest_generator_seed_is_ancestor_of_head() -> None:
    from scripts.generate_poke_command_introductions import SEED_COMMIT

    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", SEED_COMMIT, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0


def test_manifest_generator_identifies_commands_already_in_seed() -> None:
    from scripts.generate_poke_command_introductions import (
        _command_literal_existed_at_seed,
    )

    assert _command_literal_existed_at_seed("rank.global_collection")
    assert _command_literal_existed_at_seed("seer.pet.query")
    assert _command_literal_existed_at_seed("seer.player.query")
    assert not _command_literal_existed_at_seed("never.registered.command")


def test_manifest_generator_scans_git_history_once(monkeypatch: MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Result:
        stdout = (
            "commit-a\x002026-08-01T00:00:00+00:00\n"
            '+    id="help"\n'
            "commit-b\x002026-08-02T00:00:00+00:00\n"
            '+    id="seer.autocard.sanctuary"\n'
        )

    def fake_run(args: list[str], **_kwargs: Any) -> Result:
        calls.append(args)
        return Result()

    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions.subprocess.run",
        fake_run,
    )
    from scripts.generate_poke_command_introductions import _introduced_timestamps

    assert _introduced_timestamps(("help", "seer.autocard.sanctuary")) == {
        "help": "2026-08-01T00:00:00+00:00",
        "seer.autocard.sanctuary": "2026-08-02T00:00:00+00:00",
    }
    assert len(calls) == 1


def test_manifest_generator_uses_checked_in_seed_without_archive(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed = tmp_path / "poke-command-introductions.json"
    seed.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "commands": {"legacy.command": "2026-08-01T00:00:00+08:00"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions._git_object_exists",
        lambda _revision: False,
    )
    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions._git_lines",
        lambda *_args: ["ok"],
    )
    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions._introduced_timestamps",
        lambda _ids, revision: (
            {"new.command": "2026-09-23T00:00:00+08:00"}
            if revision.endswith("..HEAD")
            else {}
        ),
    )
    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions._command_literal_existed_at_seed",
        lambda _command_id: False,
    )
    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions.MANIFEST_PATH",
        seed,
    )
    from scripts.generate_poke_command_introductions import build_manifest

    manifest = build_manifest(("legacy.command", "new.command"))

    assert manifest["commands"] == {
        "legacy.command": "2026-08-01T00:00:00+08:00",
        "new.command": "2026-09-23T00:00:00+08:00",
    }


def test_reviewed_display_dates_preserve_output_and_reject_history_drift() -> None:
    from scripts.generate_poke_command_introductions import (
        _retain_reviewed_display_dates,
    )

    commands = {
        "seer.player.identity.begin": "2026-09-15T03:32:09+08:00",
        "about.official_identity_info": "2026-09-15T19:24:00+08:00",
        "unrelated": "2026-09-15T01:00:00+08:00",
    }
    _retain_reviewed_display_dates(commands)
    assert commands == {
        "seer.player.identity.begin": "2026-09-15T04:08:49+08:00",
        "about.official_identity_info": "2026-09-15T21:28:37+08:00",
        "unrelated": "2026-09-15T01:00:00+08:00",
    }

    commands["seer.player.identity.begin"] = "2026-09-15T05:00:00+08:00"
    with pytest.raises(ValueError, match=r"seer\.player\.identity\.begin"):
        _retain_reviewed_display_dates(commands)
