from __future__ import annotations

import sys

import pytest

from ironsbot.app.nonebot_manifest import (
    PluginManifestProfile,
    nonebot_manifest_path,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@pytest.mark.parametrize("profile", ("full", "core"))
def test_bundled_nonebot_manifest_declares_local_bootstrap(
    profile: PluginManifestProfile,
) -> None:
    path = nonebot_manifest_path(profile)

    document = tomllib.loads(path.read_text(encoding="utf-8"))

    assert document["tool"]["nonebot"]["plugin_dirs"] == []
    assert document["tool"]["nonebot"]["plugins"] == {
        "@local": [
            "nonebot_plugin_saa",
            "ironsbot.plugins.onebot.bootstrap",
            "ironsbot.plugins.about",
            "ironsbot.plugins.help",
            "ironsbot.plugins.help.hint",
            "ironsbot.plugins.sendpic",
            "ironsbot.plugins.messaging.blacklist",
            "ironsbot.plugins.messaging.meeting",
            "ironsbot.plugins.messaging.red_packet",
            "ironsbot.plugins.fire_manual_ad",
            "ironsbot.plugins.seer.rank_help",
            "ironsbot.plugins.team_audit",
            "ironsbot.plugins.team.resource",
            "ironsbot.plugins.activity",
            "ironsbot.plugins.headless_seer_notice",
        ]
    }
