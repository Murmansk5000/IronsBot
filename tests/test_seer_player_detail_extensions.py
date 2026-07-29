from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.query_result import QueryReply


def _action(
    *,
    label: str = "阵容",
    aliases: tuple[str, ...] = ("阵容",),
) -> PlayerDetailExtensionAction:
    return PlayerDetailExtensionAction(
        id="lineup",
        feature="player_lineup_private",
        label=label,
        aliases=aliases,
        query=AsyncMock(return_value=QueryReply(text="ok")),
        action=ActionDefinition("lineup", "阵容"),
    )


@pytest.mark.parametrize(
    ("label", "aliases", "message"),
    [
        ("【阵容】", ("阵容",), "must not include menu brackets"),
        ("阵容", ("4", "阵容"), "must not declare menu numbers"),
        ("阵容", ("收集",), "overlap built-ins"),
        ("阵容", (), "requires aliases"),
    ],
)
def test_extension_actions_reject_menu_presentation_fields(
    label: str,
    aliases: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PlayerDetailExtensionRegistry().register(_action(label=label, aliases=aliases))


def test_extension_actions_resolve_only_their_registered_aliases() -> None:
    registry = PlayerDetailExtensionRegistry()
    registry.register(_action())

    assert registry.resolve_alias("阵容", allowed_ids=("lineup",)) is not None
    assert registry.resolve_alias("阵容", allowed_ids=()) is None
