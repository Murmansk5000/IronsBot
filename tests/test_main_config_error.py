from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ERROR_EXIT_CODE = 2


def test_module_execution_reports_missing_config_without_traceback(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing" / "ironsbot.toml"

    result = subprocess.run(
        [sys.executable, "-m", "ironsbot"],
        cwd=ROOT,
        env={**os.environ, "APP_CONFIG_PATH": str(missing_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )

    assert result.returncode == CONFIG_ERROR_EXIT_CODE
    assert "未找到 IronsBot 配置文件" in result.stderr
    assert str(missing_path) in result.stderr
    assert "Traceback" not in result.stderr
