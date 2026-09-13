from unittest.mock import Mock

import pytest

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.data_query_commands import NEW_AUTOCARD_CARDS_COMMANDS
from ironsbot.services.seer.query_commands import AUTOCARD_QUERY


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

