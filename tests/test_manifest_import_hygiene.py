import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    env_keys = (
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    )
    env = {
        key: value
        for key in env_keys
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "AI_KEY": "",
            "APP_CONFIG_PATH": str(ROOT / "config.example.toml"),
            "DRIVER": "~fastapi+~httpx",
            "ENVIRONMENT": "test",
            "HEADLESS_SEER_PASSWORD": "",
            "HEADLESS_SEER_USER_ID": "",
            "LOG_LEVEL": "WARNING",
            "ONEBOT_ACCESS_TOKEN": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT),
            "SENDPIC_CNB_TOKEN": "",
            "SUPERUSERS": "[]",
        }
    )
    return env


def test_manifest_plugin_imports_have_no_runtime_side_effects(
    tmp_path: Path,
) -> None:
    script = r"""
import asyncio
import os
import pathlib
import sqlite3
import sys

import httpx
import nonebot

from ironsbot.app.plugin_manifest import (
    validate_plugin_manifest,
)
from ironsbot.app.command_cooldown_manifest import (
    setup_command_cooldown_manifest_runtime,
)
from ironsbot.plugin_catalog import plugin_modules_for_group

os.chdir(sys.argv[1])
nonebot.init()
validate_plugin_manifest()

for module in plugin_modules_for_group("external"):
    plugin = nonebot.load_plugin(module)
    if plugin is None:
        raise AssertionError(f"failed to load plugin: {module}")


def _forbidden_sync(action):
    def _forbidden(*args, **kwargs):
        raise AssertionError(f"{action} at plugin import time")

    return _forbidden


async def _forbidden_async_request(*args, **kwargs):
    raise AssertionError("http request at plugin import time")


pathlib.Path.mkdir = _forbidden_sync("directory creation")
os.mkdir = _forbidden_sync("directory creation")
os.makedirs = _forbidden_sync("directory creation")
sqlite3.connect = _forbidden_sync("sqlite open")
asyncio.create_task = _forbidden_sync("async task creation")
httpx.Client.request = _forbidden_sync("http request")
httpx.AsyncClient.request = _forbidden_async_request

for group in ("core", "infrastructure", "feature"):
    for module in plugin_modules_for_group(group):
        plugin = nonebot.load_plugin(module)
        if plugin is None:
            raise AssertionError(f"failed to load plugin: {module}")

setup_command_cooldown_manifest_runtime()
setup_command_cooldown_manifest_runtime()

runtime_paths = [
    pathlib.Path("data"),
    pathlib.Path("cache"),
    pathlib.Path("render_cache"),
]
created_paths = [path.as_posix() for path in runtime_paths if path.exists()]
created_db_files = [
    path.as_posix()
    for path in pathlib.Path(".").rglob("*")
    if path.is_file() and path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}
]
if created_paths or created_db_files:
    raise AssertionError(
        "runtime storage created at plugin import time: "
        + ", ".join([*created_paths, *created_db_files])
    )

print("manifest import hygiene ok")
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=ROOT,
        env=_subprocess_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "manifest import hygiene ok" in result.stdout
