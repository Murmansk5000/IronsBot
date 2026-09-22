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
    assert manifest["baseline_commit"] == "b97cb3ec"
    assert "seer.autocard.sanctuary" in manifest["commands"]
    assert "help" in manifest["commands"]


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
