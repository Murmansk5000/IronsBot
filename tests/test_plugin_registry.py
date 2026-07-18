from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot
import tomli

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.app.composition import build_application_lifecycle
from ironsbot.app.registry import validate_plugin_registry
from ironsbot.core.features import Feature
from tests.helpers.plugin_registry import build_test_plugin_registry

DEFINITIONS = build_test_plugin_registry()
DEFINITIONS_BY_ID = {definition.id: definition for definition in DEFINITIONS}


def test_plugin_registry_validates() -> None:
    validate_plugin_registry(DEFINITIONS)


def test_plugin_registry_is_the_feature_authority() -> None:
    owned_features = {
        feature
        for definition in DEFINITIONS
        for feature in definition.features
    }

    assert owned_features == set(Feature)
    assert len(DEFINITIONS_BY_ID) == len(DEFINITIONS)


def test_registry_installs_foundation_before_dependents() -> None:
    plugin_ids = tuple(definition.id for definition in DEFINITIONS)

    assert plugin_ids.index("http_client") < plugin_ids.index("seer_data")
    assert plugin_ids.index("db_sync") < plugin_ids.index("seer_data")
    assert plugin_ids.index("seer_data") < plugin_ids.index("seer_query")


def test_registry_is_the_lifecycle_order_authority() -> None:
    lifecycle = build_application_lifecycle(
        cast("Driver", object()),
        DEFINITIONS,
    )

    assert [name for name, _hook in lifecycle.startup_hooks] == [
        "http_client",
        "docker_update",
        "db_sync",
        "headless_seer",
        "messaging",
        "headless_reconnect_jobs",
        "scheduled_restart_jobs",
        "bilibili_monitor_jobs",
        "activity_reminder_jobs",
        "team_resource_jobs",
        "local_rank_jobs",
        "rank_page_jobs",
    ]
    assert [name for name, _hook in lifecycle.shutdown_hooks] == [
        "http_client",
        "headless_seer",
        "activity",
    ]
    assert [name for name, _hook in lifecycle.first_bot_connect_hooks] == [
        "headless_seer_check",
        "bilibili_check",
        "startup_notice",
        "render_crash_report",
    ]
    assert [name for name, _hook in lifecycle.bot_connect_hooks] == [
        "team_audit_followups",
    ]


def test_internal_plugins_use_only_the_matcher_registry() -> None:
    forbidden_imports = {
        "MatcherGroup",
        "PluginMetadata",
        "on_command",
        "on_fullmatch",
        "on_message",
        "on_notice",
    }
    violations: list[str] = []

    for path in sorted((ROOT / "ironsbot" / "plugins").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "nonebot",
                "nonebot.plugin",
                "nonebot.plugin.on",
            }:
                imported = forbidden_imports.intersection(
                    alias.name for alias in node.names
                )
                if imported:
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {sorted(imported)}"
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "nonebot"
                and node.func.attr in forbidden_imports
            ):
                violations.append(
                    f"{path.relative_to(ROOT)} calls nonebot.{node.func.attr}"
                )

    assert violations == []


def test_pyproject_does_not_define_plugin_loading_lists() -> None:
    pyproject = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    nonebot_config = pyproject["tool"]["nonebot"]

    assert nonebot_config.get("plugin_dirs") == []
    assert nonebot_config.get("builtin_plugins") == []
    assert "plugins" not in nonebot_config
