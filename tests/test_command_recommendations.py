from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

from ironsbot.config.models.features import HelpConfig
from ironsbot.core.command_catalog import CommandContext, CommandContract
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.messaging.command_recommendations import (
    CommandRecommendationService,
    load_introductions,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService


@pytest.mark.parametrize(("days", "expected"), [(0, 5), (5, 3), (10, 2)])
def test_extra_weight_halves_without_repromoting_old_ids(
    days: int, expected: float
) -> None:
    introduced = datetime(2026, 8, 11, tzinfo=timezone.utc)
    service = CommandRecommendationService(
        cast("CommandCatalog", Mock()),
        cast("FeatureService", Mock()),
        HelpConfig(),
        {"new": introduced},
    )
    now = introduced + timedelta(days=days)
    assert service.weight("new", now) == expected
    assert service.weight("old", now) == 1


def test_recommendation_uses_filtered_catalog_and_help_fallback() -> None:
    catalog, features = Mock(), Mock()
    service = CommandRecommendationService(
        cast("CommandCatalog", catalog),
        cast("FeatureService", features),
        HelpConfig(ignored_plugins=["hidden"]),
        {},
    )
    context = CommandContext(
        ActorRef(Platform.ONEBOT, "123"),
        ConversationRef(Platform.ONEBOT, "group", "456"),
    )
    catalog.poke_candidates_for_context.return_value = []
    assert service.reply(context) == DIRECT_COMMAND_HELP_HINT_TEXT
    catalog.poke_candidates_for_context.assert_called_once_with(
        context,
        features,
        ignored_plugins=["hidden"],
    )
    command = CommandContract(
        "allowed", "query", "query", ("精灵雷伊",), "资料", show_in_poke=True
    )
    catalog.poke_candidates_for_context.return_value = [command]
    assert service.reply(context).startswith(command.poke_text())


def test_missing_manifest_warns_and_returns_uniform_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert load_introductions(tmp_path / "missing.json") == {}
    assert "uniform weights" in caplog.text
