import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.ai_chat import AI_CHAT_PRIORITY
from ironsbot.plugins.seer.query.group import matcher_group


def test_ai_chat_runs_after_seer_query_matchers() -> None:
    seer_query_priority = matcher_group.base_kwargs["priority"]

    assert seer_query_priority < AI_CHAT_PRIORITY
