from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot
import tomllib

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.config.models.operations import StartupConfig
    from ironsbot.services.operations.startup import StartupNoticeService

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.config.models.settings import Settings
from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    OPTIONAL_PRIVATE_FEATURES,
    validate_plugin_contributions,
)
from ironsbot.plugins.onebot.startup_notice import (
    plugin_contribution as startup_notice_plugin_contribution,
)
from ironsbot.services.ai.command_contracts import (
    ai_chat_command_contracts,
    ai_intent_command_contracts,
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
        feature for definition in DEFINITIONS for feature in definition.features
    }

    assert owned_features | OPTIONAL_PRIVATE_FEATURES == set(Feature)
    assert len(DEFINITIONS_BY_ID) == len(DEFINITIONS)


def test_manifest_sendpic_owns_its_command_contracts() -> None:
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


def test_manifest_help_hint_owns_its_passive_matcher() -> None:
    contribution = DEFINITIONS_BY_ID["help_hint"]

    assert contribution.features == frozenset()
    assert contribution.commands == ()


def test_manifest_rank_help_owns_its_command_contracts() -> None:
    contribution = DEFINITIONS_BY_ID["rank_help"]

    assert contribution.features == frozenset({Feature.SEER_RANK})
    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"rank_help"}


def test_manifest_pet_config_owns_its_command_descriptor() -> None:
    contribution = DEFINITIONS_BY_ID["pet_config"]

    assert contribution.features == frozenset({Feature.PET_CONFIG})
    assert {command.plugin_id for command in contribution.commands} == {"pet_config"}


def test_manifest_team_audit_owns_its_feature_and_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["team_audit"]

    assert contribution.features == frozenset({Feature.TEAM_AUDIT})
    assert contribution.commands == ()
    assert [name for name, _hook in contribution.hooks.bot_connect] == [
        "team_audit_followups"
    ]


def test_manifest_team_resource_owns_its_commands_and_schedule() -> None:
    contribution = DEFINITIONS_BY_ID["team_resource"]

    assert contribution.features == frozenset({Feature.TEAM_RESOURCE_SUBSCRIPTION})
    assert {command.plugin_id for command in contribution.commands} == {"team_resource"}
    assert [name for name, _hook in contribution.hooks.startup] == [
        "team_resource_jobs"
    ]


def test_manifest_activity_owns_its_commands_and_schedule() -> None:
    contribution = DEFINITIONS_BY_ID["activity"]

    assert contribution.features == frozenset(
        {Feature.SEER_ACTIVITY_QUERY, Feature.SEER_ACTIVITY_PUSH}
    )
    assert {command.plugin_id for command in contribution.commands} == {"activity"}
    assert [name for name, _hook in contribution.hooks.startup] == [
        "activity_reminder_jobs"
    ]


def test_manifest_data_sync_owns_only_its_onebot_commands() -> None:
    contribution = DEFINITIONS_BY_ID["db_sync"]

    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"db_sync"}
    assert contribution.hooks.startup == ()


def test_manifest_bilibili_owns_its_commands_and_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["bilibili"]

    assert contribution.features == frozenset({Feature.BILI_QUERY, Feature.BILI_PUSH})
    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"bilibili"}
    assert [name for name, _hook in contribution.hooks.startup] == [
        "bilibili_monitor_jobs"
    ]
    assert [name for name, _hook in contribution.hooks.first_bot_connect] == [
        "bilibili_check"
    ]


def test_manifest_messaging_owns_its_commands_and_schedule() -> None:
    contribution = DEFINITIONS_BY_ID["messaging"]

    assert contribution.features == frozenset(
        {
            Feature.TEXT,
            Feature.TEXT_PUSH,
            Feature.WEB_ACTIVITY_LINK,
            Feature.WEB_ACTIVITY_PUSH,
            Feature.SEERINFO,
        }
    )
    assert {command.plugin_id for command in contribution.commands} == {"messaging"}
    assert [name for name, _hook in contribution.hooks.startup] == ["messaging"]


def test_manifest_ai_chat_owns_its_features_and_commands() -> None:
    contribution = DEFINITIONS_BY_ID["ai_chat"]

    assert contribution.features == frozenset({Feature.AI_CHAT, Feature.ADMIN_NOTICE})
    assert contribution.commands == ()
    assert {
        command.plugin_id for command in ai_chat_command_contracts(enabled=True)
    } == {"ai_chat"}


def test_manifest_ai_intent_owns_its_features_and_commands() -> None:
    contribution = DEFINITIONS_BY_ID["ai_intent"]

    assert contribution.features == frozenset(
        {
            Feature.AI_INTENT,
            Feature.AI_INTENT_TEAM_RECOMMEND,
            Feature.AI_INTENT_FIRE_MANUAL,
        }
    )
    assert contribution.commands == ()
    assert not ai_intent_command_contracts(
        Settings.model_validate(
            {
                "ai": {
                    "providers": {
                        "test": {
                            "api_key": "test",
                            "base_url": "https://example.test/v1",
                            "models": ["test-model"],
                        }
                    }
                }
            }
        )
    )
    enabled_settings = Settings.model_validate(
        {
            "promotions": {
                "manual": {
                    "feature": "fire_manual_ad",
                    "text": "手册：{url}",
                }
            },
            "ai": {
                "providers": {
                    "test": {
                        "api_key": "test",
                        "base_url": "https://example.test/v1",
                        "models": ["test-model"],
                    }
                },
                "intent_actions": {
                    "manual": {
                        "feature": "ai_intent_fire_manual",
                        "keywords": ["手册"],
                        "action": "promotion",
                        "promotion": "manual",
                        "intent": "判断用户是否索要手册链接。",
                    }
                },
            },
        }
    )
    assert {
        command.plugin_id for command in ai_intent_command_contracts(enabled_settings)
    } == {"ai_intent"}


def test_manifest_server_status_owns_its_commands_and_feature() -> None:
    contribution = DEFINITIONS_BY_ID["server_status"]

    assert contribution.features == frozenset({Feature.SERVER_STATUS_QUERY})
    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"server_status"}


def test_manifest_docker_update_owns_its_commands_and_startup_hook() -> None:
    contribution = DEFINITIONS_BY_ID["docker_update"]

    assert contribution.commands
    assert {command.plugin_id for command in contribution.commands} == {"docker_update"}
    assert [name for name, _hook in contribution.hooks.startup] == ["docker_update"]


def test_manifest_lucky_skin_window_owns_its_commands_and_schedule() -> None:
    contribution = DEFINITIONS_BY_ID["lucky_skin_window"]

    assert contribution.features == frozenset({Feature.LUCKY_SKIN_WINDOW})
    assert {command.plugin_id for command in contribution.commands} == {
        "lucky_skin_window"
    }
    assert [name for name, _hook in contribution.hooks.startup] == [
        "lucky_skin_window_schedule"
    ]


def test_manifest_headless_notice_owns_its_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["headless_notice"]

    assert contribution.commands == ()
    assert [name for name, _hook in contribution.hooks.startup] == [
        "headless_reconnect_jobs"
    ]
    assert [name for name, _hook in contribution.hooks.first_bot_connect] == [
        "headless_seer_check"
    ]


def test_manifest_startup_notice_owns_its_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["startup_notice"]

    assert contribution.commands == ()
    assert [name for name, _hook in contribution.hooks.first_bot_connect] == [
        "startup_notice"
    ]


def test_official_startup_notice_does_not_wait_for_onebot_connect() -> None:
    base = DEFINITIONS_BY_ID["startup_notice"]
    contribution = startup_notice_plugin_contribution(
        service=cast("StartupNoticeService", object()),
        config=cast("StartupConfig", object()),
        send_on_startup=True,
    )

    assert base.hooks.startup == ()
    assert [name for name, _hook in contribution.hooks.startup] == [
        "startup_notice"
    ]
    assert [name for name, _hook in contribution.hooks.first_bot_connect] == [
        "startup_notice"
    ]


def test_manifest_headless_runtime_owns_its_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["headless_seer"]

    assert contribution.commands == ()
    assert [name for name, _hook in contribution.hooks.startup] == ["headless_seer"]
    assert [name for name, _hook in contribution.hooks.shutdown] == ["headless_seer"]


def test_manifest_scheduled_restart_owns_its_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["scheduled_restart"]

    assert contribution.commands == ()
    assert [name for name, _hook in contribution.hooks.startup] == [
        "scheduled_restart_jobs"
    ]


def test_manifest_scheduler_owns_its_lifecycle() -> None:
    contribution = DEFINITIONS_BY_ID["scheduler"]

    assert contribution.commands == ()
    assert [name for name, _hook in contribution.hooks.startup] == ["scheduler"]
    assert [name for name, _hook in contribution.hooks.shutdown] == ["scheduler"]


def test_manifest_contributions_follow_the_legacy_bridge() -> None:
    plugin_ids = tuple(definition.id for definition in DEFINITIONS)

    assert plugin_ids[0] == "scheduler"
    assert plugin_ids.index("seer_query") < plugin_ids.index("bilibili")
    assert plugin_ids.index("bilibili") < plugin_ids.index("messaging")
    assert plugin_ids.index("messaging") < plugin_ids.index("ai_chat")
    assert plugin_ids.index("ai_chat") < plugin_ids.index("ai_intent")
    assert plugin_ids.index("ai_intent") < plugin_ids.index("server_status")
    assert plugin_ids.index("server_status") < plugin_ids.index("docker_update")
    assert plugin_ids.index("docker_update") < plugin_ids.index("db_sync")


def test_contributions_define_the_lifecycle_order() -> None:
    lifecycle = ApplicationLifecycle.from_contributions(
        cast("Driver", object()),
        DEFINITIONS,
        task_owner=TaskOwner(),
    )

    assert [name for name, _hook in lifecycle.startup_hooks] == [
        "scheduler",
        "local_rank_jobs",
        "rank_page_jobs",
        "bilibili_monitor_jobs",
        "messaging",
        "docker_update",
        "lucky_skin_window_schedule",
        "team_resource_jobs",
        "activity_reminder_jobs",
        "headless_reconnect_jobs",
        "headless_seer",
        "scheduled_restart_jobs",
    ]
    assert [name for name, _hook in lifecycle.shutdown_hooks] == [
        "scheduler",
        "headless_seer",
    ]
    assert [name for name, _hook in lifecycle.first_bot_connect_hooks] == [
        "render_crash_report",
        "bilibili_check",
        "startup_notice",
        "headless_seer_check",
    ]
    assert [name for name, _hook in lifecycle.bot_connect_hooks] == [
        "team_audit_followups",
    ]


def test_internal_plugins_use_only_the_matcher_factory() -> None:
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
                    ROOT / "ironsbot" / "plugins" / "onebot" / "about" / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "help" / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "help" / "hint.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "sendpic"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "pet_config"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "messaging"
                    / "blacklist.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "messaging"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "messaging"
                    / "meeting.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "messaging"
                    / "red_packet.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "bilibili"
                    / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "ai" / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "ai" / "intent.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "fire_manual_ad"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "seer"
                    / "rank_help"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "seer"
                    / "query"
                    / "__init__.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "lucky_skin_window.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "team_audit.py",
                    ROOT / "ironsbot" / "plugins" / "onebot" / "team_resource.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "activity"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "operations"
                    / "db_sync.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "operations"
                    / "docker_update.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "operations"
                    / "server_status.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "startup_notice"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "headless_seer_notice"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "headless_seer_runtime"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "scheduled_restart"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "scheduler"
                    / "__init__.py",
                    ROOT
                    / "ironsbot"
                    / "plugins"
                    / "onebot"
                    / "clock_check"
                    / "__init__.py",
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
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    nonebot_config = pyproject["tool"]["nonebot"]

    assert nonebot_config.get("plugin_dirs") == []
    assert nonebot_config.get("builtin_plugins") == []
    assert "plugins" not in nonebot_config
