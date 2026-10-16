# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def test_real_history_without_archive_preserves_reviewed_seed(
    monkeypatch: MonkeyPatch,
) -> None:
    from scripts.generate_poke_command_introductions import (
        MANIFEST_PATH,
        SEED_COMMIT,
        build_manifest,
    )

    monkeypatch.setattr(
        "scripts.generate_poke_command_introductions._git_object_exists",
        lambda _revision: False,
    )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", SEED_COMMIT, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert ancestor.returncode == 0
    seed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["commands"]
    original = {
        "about.official_identity_info": "2026-09-15T21:28:37+08:00",
        "activity.new": "2026-08-15T11:17:31+08:00",
        "seer.autocard.sanctuary": "2026-08-11T17:32:19+08:00",
        "seer.data.peak_environment_changes": "2026-08-14T23:15:23+08:00",
        "seer.pet.avatar": "2026-09-04T13:32:39+08:00",
        "seer.player.identity.begin": "2026-09-15T04:08:49+08:00",
        "seer.player.identity.confirm": "2026-09-15T04:08:49+08:00",
        "seer.player.identity.revoke": "2026-09-15T04:08:49+08:00",
        "seer.player.identity.status": "2026-09-15T04:08:49+08:00",
    }
    assert {key: seed[key] for key in original} == original
    assert seed["seer.pet.flip"] == "2026-09-23T20:09:13+08:00"
    later = {
        "rank.global_collection": "2026-09-23T22:08:31+08:00",
        "seer.player.query": "2026-09-23T22:08:31+08:00",
        "seer.pet.query": "2026-09-26T10:58:34+08:00",
        "seer.lucky_skin_window.query": "2026-10-16T11:17:53+08:00",
    }
    assert build_manifest((*seed, *later))["commands"] == {**seed, **later}


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
        "scripts.generate_poke_command_introductions.MANIFEST_PATH",
        seed,
    )
    from scripts.generate_poke_command_introductions import build_manifest

    manifest = build_manifest(("legacy.command", "new.command"))

    assert manifest["commands"] == {
        "legacy.command": "2026-08-01T00:00:00+08:00",
        "new.command": "2026-09-23T00:00:00+08:00",
    }
