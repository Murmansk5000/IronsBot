from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_application_bootstrap_smoke() -> None:
    script = """
import os

os.environ["APP_CONFIG_PATH"] = "config.example.toml"

from nonebot.log import logger

logger.remove()

from ironsbot.app.bootstrap import bootstrap

state = bootstrap()
assert state.lifecycle is not None
assert len(state.plugins) > 0
assert len(state.matchers.message_matchers) > 0
assert len(state.matchers.notice_matchers) > 0
assert len({plugin.id for plugin in state.plugins}) == len(state.plugins)
print("BOOTSTRAP_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "BOOTSTRAP_OK"
