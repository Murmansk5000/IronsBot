# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
    assert manifest["baseline_commit"] == "f53f7dae"
    assert "seer.autocard.sanctuary" in manifest["commands"]
    assert "help" not in manifest["commands"]
