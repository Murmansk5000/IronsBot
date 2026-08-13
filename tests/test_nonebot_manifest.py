from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ironsbot.app.nonebot_manifest import (
    PluginManifestProfile,
    nonebot_manifest_path,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def test_project_nonebot_adapter_matches_the_onebot_v11_runtime() -> None:
    document = tomllib.loads((Path("pyproject.toml")).read_text(encoding="utf-8"))

    assert document["tool"]["nonebot"]["adapters"]["nonebot-adapter-onebot"] == [
        {
            "name": "OneBot V11",
            "module_name": "nonebot.adapters.onebot.v11",
        }
    ]


FULL_PLUGINS = [
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_htmlkit",
    "nonebot_plugin_saa",
    "ironsbot.plugins.onebot.scheduler",
    "ironsbot.plugins.onebot.seer.query",
    "ironsbot.plugins.onebot.bilibili",
    "ironsbot.plugins.onebot.messaging",
    "ironsbot.plugins.onebot.ai",
    "ironsbot.plugins.onebot.ai.intent",
    "ironsbot.plugins.onebot.operations.server_status",
    "ironsbot.plugins.onebot.operations.docker_update",
    "ironsbot.plugins.onebot.operations.db_sync",
    "ironsbot.plugins.onebot.about",
    "ironsbot.plugins.onebot.help",
    "ironsbot.plugins.onebot.help.hint",
    "ironsbot.plugins.onebot.sendpic",
    "ironsbot.plugins.onebot.messaging.blacklist",
    "ironsbot.plugins.onebot.messaging.meeting",
    "ironsbot.plugins.onebot.messaging.red_packet",
    "ironsbot.plugins.onebot.fire_manual_ad",
    "ironsbot.plugins.onebot.seer.rank_help",
    "ironsbot.plugins.onebot.pet_config",
    "ironsbot.plugins.onebot.lucky_skin_window",
    "ironsbot.plugins.onebot.team_audit",
    "ironsbot.plugins.onebot.team_resource",
    "ironsbot.plugins.onebot.activity",
    "ironsbot.plugins.onebot.startup_notice",
    "ironsbot.plugins.onebot.headless_seer_notice",
    "ironsbot.plugins.onebot.headless_seer_runtime",
    "ironsbot.plugins.onebot.scheduled_restart",
]

CORE_PLUGINS = [
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_htmlkit",
    "nonebot_plugin_saa",
    "ironsbot.plugins.onebot.scheduler",
    "ironsbot.plugins.onebot.seer.query",
    "ironsbot.plugins.onebot.about",
    "ironsbot.plugins.onebot.help",
    "ironsbot.plugins.onebot.help.hint",
    "ironsbot.plugins.onebot.seer.rank_help",
]


@pytest.mark.parametrize(
    ("profile", "expected_plugins"),
    (("full", FULL_PLUGINS), ("core", CORE_PLUGINS)),
)
def test_bundled_nonebot_manifest_declares_local_plugins(
    profile: PluginManifestProfile,
    expected_plugins: list[str],
) -> None:
    path = nonebot_manifest_path(profile)

    document = tomllib.loads(path.read_text(encoding="utf-8"))

    assert document["tool"]["nonebot"]["plugin_dirs"] == []
    assert document["tool"]["nonebot"]["plugins"] == {"@local": expected_plugins}


def test_core_manifest_is_a_strict_subset_of_full() -> None:
    assert set(CORE_PLUGINS) < set(FULL_PLUGINS)


@pytest.mark.parametrize(
    "profile",
    ("full", "core"),
)
def test_bundled_nonebot_manifest_keeps_internal_plugins_in_onebot_adapter(
    profile: PluginManifestProfile,
) -> None:
    document = tomllib.loads(nonebot_manifest_path(profile).read_text(encoding="utf-8"))
    local_plugins = document["tool"]["nonebot"]["plugins"]["@local"]
    internal_plugins = [
        plugin for plugin in local_plugins if plugin.startswith("ironsbot.plugins.")
    ]

    assert internal_plugins
    assert all(
        plugin.startswith("ironsbot.plugins.onebot.") for plugin in internal_plugins
    )
