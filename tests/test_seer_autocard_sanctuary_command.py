from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

import pytest

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import Platform
from ironsbot.services.portable_autocard_commands import (
    build_portable_autocard_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.autocard_sanctuary import (
    Sanctuary,
    SanctuaryEffect,
    SanctuaryEffectEntry,
    SanctuaryPromptValue,
    SanctuarySearchResult,
)
from tests.test_portable_menu_navigation import context


def _sanctuary() -> Sanctuary:
    return Sanctuary(
        id=2,
        name="沧岚",
        pet_id=3105,
        pet_name="沧岚",
        effects=(
            SanctuaryEffect(8, 2, "沧岚", "基础效果", 0, 0),
            SanctuaryEffect(9, 2, "潮涌", "祝印效果", 5, 1),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_sanctuary_menu_and_effect_selection_share_public_sessions(
    platform: Platform,
) -> None:
    service = Mock(
        search=Mock(return_value=SanctuarySearchResult(sanctuary=_sanctuary())),
        select=Mock(
            return_value=SanctuarySearchResult(
                effect=SanctuaryEffectEntry(9, "潮涌", "完整祝印描述"),
            )
        ),
    )
    sessions = PortableQuerySessions()
    current = context(platform)
    operation = build_portable_autocard_operations(
        Mock(),
        Mock(),
        cast("Any", service),
        sessions,
    )["seer.autocard.sanctuary"]
    menu = await operation("群星牌场地沧岚", current)
    assert isinstance(menu, OutboundMessage) and menu.prompt is not None
    assert [choice.id for choice in menu.prompt.choices] == ["1", "2", "0"]
    result = await sessions.select("2", current)
    assert isinstance(result, OutboundMessage)
    assert result.parts == (TextPart("完整祝印描述"),)
    service.select.assert_called_once_with(SanctuaryPromptValue("effect", 2, 9))
    assert sessions.has_active_session(current)
