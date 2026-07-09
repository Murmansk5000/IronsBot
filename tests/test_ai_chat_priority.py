import os
from pathlib import Path

import nonebot

from ironsbot.config import clear_app_config_cache

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")
clear_app_config_cache()

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.ai_chat import AI_CHAT_PRIORITY, AI_GROUP_AT_CHAT_PRIORITY
from ironsbot.plugins.ai_mention_guard import AI_MENTION_GUARD_PRIORITY
from ironsbot.plugins.seer.query.group import matcher_group


def test_ai_chat_runs_after_seer_query_matchers() -> None:
    seer_query_priority = matcher_group.base_kwargs["priority"]

    assert seer_query_priority < AI_CHAT_PRIORITY


def test_group_at_matchers_run_before_seer_query_matchers() -> None:
    seer_query_priority = matcher_group.base_kwargs["priority"]

    assert seer_query_priority > AI_GROUP_AT_CHAT_PRIORITY
    assert seer_query_priority > AI_MENTION_GUARD_PRIORITY
