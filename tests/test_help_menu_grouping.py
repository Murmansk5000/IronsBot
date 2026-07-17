import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

from ironsbot.plugin_catalog import help_layout_for_module, help_visibility_for_module
from ironsbot.plugins.help.menu import HELP_GROUP_TITLES


def test_team_entries_are_grouped_with_seer_queries() -> None:
    assert HELP_GROUP_TITLES["ai"] == "AI"
    assert help_layout_for_module("ironsbot.plugins.ai_chat")[0] == "ai"
    assert help_layout_for_module("ironsbot.plugins.ai_intent")[0] == "ai"
    assert (
        help_layout_for_module("ironsbot.plugins.team_resource_subscription")[0]
        == "seer"
    )
    assert help_layout_for_module("ironsbot.plugins.team_audit_welcome")[0] == "seer"
    assert help_layout_for_module("ironsbot.plugins.server_status")[0] == "seer"


def test_image_sender_is_hidden_from_top_level_help() -> None:
    assert help_visibility_for_module("ironsbot.plugins.sendpic") == "hidden"
