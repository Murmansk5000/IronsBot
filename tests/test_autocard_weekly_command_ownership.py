from dataclasses import replace
from unittest.mock import Mock

import pytest

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.portable_new_content_commands import (
    build_portable_new_content_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.data_query_commands import NEW_AUTOCARD_CARDS_COMMANDS
from ironsbot.services.seer.new_content import NewContentCategoryState, NewContentItem
from ironsbot.services.seer.query_commands import AUTOCARD_QUERY
from tests.test_portable_new_content_commands import (
    _context,
    _features,
    _MenuRenderer,
    _resources,
    _snapshot,
)


@pytest.mark.parametrize("command", NEW_AUTOCARD_CARDS_COMMANDS)
def test_weekly_autocard_alias_is_not_a_card_name(command: str) -> None:
    assert AUTOCARD_QUERY(command) is None
    actor = ActorRef(Platform.QQ_OFFICIAL, "test-user")
    context = CommandContext(
        actor, ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id)
    )
    contracts = seer_command_contracts(Mock())
    owners = [c.id for c in contracts if c.matches_direct_input(context, command)]
    assert owners == ["seer.data.new_autocard"]


@pytest.mark.parametrize("command", ["洛奇亚群星牌", "群星牌洛奇亚", "群星牌210"])
def test_regular_card_queries_remain_supported(command: str) -> None:
    assert AUTOCARD_QUERY(command) is not None


@pytest.mark.asyncio
async def test_weekly_command_returns_combined_card_and_chip_menu() -> None:
    snapshot = replace(
        _snapshot(),
        items=(
            NewContentItem("autocard_card", 208, "麦索瑞尔", 208, {}, "modified"),
            NewContentItem("autocard_chip", 115, "复苏之风", 115, {}, "modified"),
        ),
        category_states=tuple(
            NewContentCategoryState(category, comparison_ready=True, reason="ready")
            for category in (
                "autocard_card",
                "autocard_role",
                "autocard_chip",
                "autocard_sanctuary_effect",
            )
        ),
    )
    renderer = _MenuRenderer()
    operations = build_portable_new_content_operations(
        _resources(snapshot, renderer),
        PortableQuerySessions(),
        _features("seer_data", "seer_autocard"),
    )
    reply = await operations["seer.data.new_autocard"](
        "新增群星牌", _context("新增群星牌")
    )
    assert isinstance(reply, OutboundMessage)
    assert any(isinstance(part, BinaryImagePart) for part in reply.parts)
    assert renderer.calls == [(("autocard_card", "autocard_chip"), None)]
