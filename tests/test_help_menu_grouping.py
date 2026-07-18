import os
from pathlib import Path

import nonebot

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.app.registry import build_plugin_registry
from ironsbot.plugins.help.menu import HELP_GROUP_TITLES

DEFINITIONS = {
    definition.id: definition
    for definition in build_plugin_registry()
}


def _help_group(plugin_id: str) -> str | None:
    entry = DEFINITIONS[plugin_id].help
    return entry.group if entry is not None else None


def test_help_groups_come_from_plugin_definitions() -> None:
    assert HELP_GROUP_TITLES["ai"] == "AI"
    assert _help_group("ai_chat") == "ai"
    assert _help_group("ai_intent") == "ai"
    assert _help_group("team_resource") == "seer"
    assert _help_group("server_status") == "seer"


def test_hidden_plugins_have_no_help_entry() -> None:
    assert DEFINITIONS["sendpic"].help is None
    assert DEFINITIONS["team_audit"].help is None
