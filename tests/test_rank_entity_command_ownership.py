from unittest.mock import Mock

import pytest

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_commands import AUTOCARD_QUERY
from ironsbot.services.seer.query_guards import is_rank_query_text
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize(
    "text",
    [
        "群星之巅榜8602分",
        "群星之巅榜8612分",
        "群星之巅榜3149分",
        "群星之巅榜123456789",
        "群星之巅榜示例玩家",
        "群星之巅榜第2页",
    ],
)
def test_rank_query_has_one_owner_across_entity_and_rank_contracts(
    platform: Platform, text: str
) -> None:
    resolver = PlayerIdResolver(
        lambda reference, _conversation: 123456789 if reference == "示例玩家" else None,
        Mock(side_effect=AssertionError("recognition must not query bindings")),
    )
    actor = ActorRef(platform, "test-user")
    context = CommandContext(actor, ConversationRef(platform, "private", actor.id))
    # Entity contracts deliberately precede rank contracts, matching production.
    contracts = (
        *seer_command_contracts(resolver),
        *rank_help_command_contracts(resolver),
    )
    owners = [
        contract.id
        for contract in contracts
        if contract.matches_direct_input(context, text)
    ]
    assert is_rank_query_text(text)
    assert AUTOCARD_QUERY(text) is None
    assert owners == ["rank.global_collection"]


@pytest.mark.parametrize("text", ["群星卡牌布布种子", "群星卡牌210", "芯片复苏之风"])
def test_normal_card_queries_are_not_reserved(text: str) -> None:
    assert not is_rank_query_text(text)
    assert AUTOCARD_QUERY(text) is not None
