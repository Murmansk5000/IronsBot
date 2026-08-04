from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot
import tomli

if TYPE_CHECKING:
    import pytest
    from nonebot.internal.driver import Driver

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.app.external_plugins import load_external_plugin
from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.features import Feature
from ironsbot.runtime.plugins import (
    OPTIONAL_PRIVATE_FEATURES,
    validate_plugin_contributions,
)
from tests.helpers.plugin_registry import build_test_plugin_registry

DEFINITIONS = build_test_plugin_registry()
DEFINITIONS_BY_ID = {definition.id: definition for definition in DEFINITIONS}


def test_plugin_registry_validates() -> None:
    validate_plugin_contributions(
        DEFINITIONS,
        required_features=frozenset(Feature),
    )


def test_plugin_contributions_cover_feature_ownership() -> None:
    owned_features = {
        feature
        for definition in DEFINITIONS
        for feature in definition.features
    }

    assert owned_features | OPTIONAL_PRIVATE_FEATURES == set(Feature)
    assert len(DEFINITIONS_BY_ID) == len(DEFINITIONS)


def test_manifest_sendpic_owns_its_command_descriptors() -> None:
    contribution = DEFINITIONS_BY_ID["sendpic"]

    assert contribution.features == frozenset({Feature.IMAGE})
    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"sendpic"}


def test_manifest_meeting_owns_its_command_descriptor() -> None:
    contribution = DEFINITIONS_BY_ID["meeting"]

    assert contribution.features == frozenset({Feature.MEETING})
    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"meeting"}


def test_manifest_blacklist_owns_its_feature() -> None:
    contribution = DEFINITIONS_BY_ID["conversation_blacklist"]

    assert contribution.features == frozenset({Feature.BLACKLIST})
    assert contribution.commands == ()


def test_manifest_red_packet_owns_its_passive_matchers() -> None:
    contribution = DEFINITIONS_BY_ID["red_packet_notice"]

    assert contribution.features == frozenset()
    assert contribution.commands == ()


def test_manifest_fire_manual_ad_owns_its_feature() -> None:
    contribution = DEFINITIONS_BY_ID["fire_manual_ad"]

    assert contribution.features == frozenset({Feature.FIRE_MANUAL_AD})
    assert contribution.commands == ()


def test_external_plugin_loading_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str] = []

    def get_plugin(_name: str) -> object:
        return object()

    def load_plugin(name: str) -> None:
        loaded.append(name)

    monkeypatch.setattr(
        "ironsbot.app.external_plugins.nonebot.get_plugin",
        get_plugin,
    )
    monkeypatch.setattr(
        "ironsbot.app.external_plugins.nonebot.load_plugin",
        load_plugin,
    )

    load_external_plugin("nonebot_plugin_saa")

    assert loaded == []


def test_registry_installs_foundation_before_dependents() -> None:
    plugin_ids = tuple(definition.id for definition in DEFINITIONS)

    assert plugin_ids[:4] == ("apscheduler", "localstore", "htmlkit", "saa")
    assert plugin_ids.index("db_sync") < plugin_ids.index("seer_query")


def test_registry_is_the_lifecycle_order_authority() -> None:
    lifecycle = ApplicationLifecycle.from_contributions(
        cast("Driver", object()),
        DEFINITIONS,
        task_owner=TaskOwner(),
    )

    assert [name for name, _hook in lifecycle.startup_hooks] == [
        "scheduler",
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
        "lucky_skin_window_schedule",
    ]
    assert [name for name, _hook in lifecycle.shutdown_hooks] == [
        "scheduler",
        "headless_seer",
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
                if path in {
                    ROOT / "ironsbot" / "plugins" / "onebot" / "bootstrap.py",
                    ROOT / "ironsbot" / "plugins" / "about" / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "help" / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "sendpic" / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "messaging" / "blacklist.py",
                    ROOT / "ironsbot" / "plugins" / "messaging" / "meeting.py",
                    ROOT / "ironsbot" / "plugins" / "messaging" / "red_packet.py",
                    ROOT / "ironsbot" / "plugins" / "fire_manual_ad" / "__init__.py",
                } and imported == {"PluginMetadata"}:
                    continue
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
