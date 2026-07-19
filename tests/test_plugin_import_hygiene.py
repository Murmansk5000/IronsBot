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
            "GITHUB_WORKFLOW_TOKEN": "",
            "ONEBOT_ACCESS_TOKEN": "",
            "HEADLESS_SEER_PASSWORD": "",
            "HEADLESS_SEER_USER_ID": "",
            "SENDPIC_CNB_TOKEN": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(ROOT),
        }
    )
    return env


def test_registry_install_has_no_storage_or_network_side_effects(
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

os.chdir(sys.argv[1])
nonebot.init()


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

from ironsbot.runtime.matchers import MatcherRegistry
from tests.helpers.plugin_registry import build_test_plugin_registry
from tests.helpers.runtime import build_test_runtime

external_ids = {"apscheduler", "localstore", "htmlkit", "saa"}
definitions = build_test_plugin_registry()
registry = build_test_runtime().matcher_registry()
for definition in definitions:
    if definition.id not in external_ids and definition.install is not None:
        definition.install(registry)
registry.install_postprocessor()

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

print("registry import hygiene ok")
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
    assert "registry import hygiene ok" in result.stdout
