from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.messaging import AiIntentAction
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.promotions import PromotionCatalog, PromotionConfig
from ironsbot.services.ai.actions import AiIntentActionExecutor


def _executor(
    *,
    ai: object | None = None,
    promotions: PromotionCatalog | None = None,
    team_resources: object | None = None,
) -> AiIntentActionExecutor:
    return AiIntentActionExecutor(
        cast("Any", ai or Mock()),
        promotions or PromotionCatalog({}),
        cast("Any", team_resources or Mock()),
    )


def _texts(messages: tuple[OutboundMessage, ...]) -> list[str]:
    return [
        part.text
        for message in messages
        for part in message.parts
        if isinstance(part, TextPart)
    ]


@pytest.mark.asyncio
async def test_team_recommend_returns_configured_messages_in_order() -> None:
    action = AiIntentAction(
        action="team_recommend",
        messages=[
            "审核群链接：https://example.com/join",
            "审核群号：123456789",
            "入群后发送米米号供管理员审核。",
        ],
    )

    messages = await _executor().execute(action, "我要加战队")

    assert _texts(messages) == action.messages


@pytest.mark.asyncio
async def test_team_resource_queries_all_configured_teams() -> None:
    team_resources = Mock(query_messages=AsyncMock(return_value=["战队一", "战队二"]))
    action = AiIntentAction(action="team_resource", team_ids=[1, 2])

    messages = await _executor(team_resources=team_resources).execute(action, "战队")

    assert _texts(messages) == ["战队一", "战队二"]
    team_resources.query_messages.assert_awaited_once_with([1, 2])


@pytest.mark.asyncio
async def test_ai_reply_forwards_source_context() -> None:
    ai = Mock(run_reply_action=AsyncMock(return_value="回答"))
    action = AiIntentAction(action="ai_reply", reply_prompt="回答：{message}")

    messages = await _executor(ai=ai).execute(
        action,
        "问题",
        source_context="来源",
    )

    assert _texts(messages) == ["回答"]
    ai.run_reply_action.assert_awaited_once_with(
        action,
        "问题",
        source_context="来源",
    )


@pytest.mark.asyncio
async def test_promotion_uses_catalog_message() -> None:
    promotions = PromotionCatalog(
        {
            "manual": PromotionConfig(
                feature="manual",
                url="https://example.test/manual",
                text="手册：{url}",
            )
        }
    )
    action = AiIntentAction(action="promotion", promotion="manual")

    messages = await _executor(promotions=promotions).execute(action, "手册")

    assert _texts(messages) == ["手册：https://example.test/manual"]
