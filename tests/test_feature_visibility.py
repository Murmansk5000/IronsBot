import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.features import Feature
from ironsbot.plugins.help import visibility
from ironsbot.shared.features import FeatureService
from tests.helpers.config import StubMessageAction, stub_app_config
from tests.helpers.onebot_events import group_message_event
from tests.helpers.plugin_registry import build_test_plugin_registry

if TYPE_CHECKING:
    from ironsbot.config.models.app import AppConfig

DEFINITIONS = {
    definition.id: definition
    for definition in build_test_plugin_registry()
}


def _group_event(text: str = "帮助"):
    return group_message_event(
        text,
        user_id=2,
        group_id=4,
    )


def _config(
    *,
    ai_intent_enabled: bool = True,
    team_resource_enabled: bool = True,
    group_actions: list[StubMessageAction] | None = None,
):
    return stub_app_config(
        ai_intent_enabled=ai_intent_enabled,
        team_resource_config=TeamResourceConfig(enabled=team_resource_enabled),
        group_actions=group_actions,
    )


def _visible(
    plugin_id: str,
    *,
    allowed_features: tuple[str, ...] = (),
    config: object | None = None,
    ai_key_configured: bool = True,
) -> bool:
    features = FeatureService(
        FeatureConfig(
            group_policy={"4": list(allowed_features)},
            superuser_bypass=False,
        ),
        frozenset(),
    )
    return visibility.plugin_visible_for_event(
        DEFINITIONS[plugin_id],
        _group_event(),
        features=features,
        config=cast("AppConfig", config or _config()),
        ai_key_configured=ai_key_configured,
    )


def test_always_visible_help_is_shown() -> None:
    assert _visible("help")


def test_plugin_definitions_own_feature_visibility() -> None:
    assert DEFINITIONS["team_audit"].features == frozenset({Feature.TEAM_AUDIT})
    assert DEFINITIONS["team_resource"].features == frozenset(
        {Feature.TEAM_RESOURCE_SUBSCRIPTION}
    )
    assert DEFINITIONS["fire_manual_ad"].features == frozenset(
        {Feature.FIRE_MANUAL_AD}
    )
    assert DEFINITIONS["ai_intent"].features == frozenset(
        {
            Feature.AI_INTENT,
            Feature.AI_INTENT_TEAM_RECOMMEND,
            Feature.AI_INTENT_FIRE_MANUAL,
        }
    )


def test_feature_visibility_uses_feature_service() -> None:
    assert _visible("seer_query", allowed_features=("seer",))
    assert not _visible("rank_help")


def test_seer_query_visible_when_any_seer_subfeature_allowed() -> None:
    assert _visible("seer_query", allowed_features=("seer_pet",))


def test_rank_help_visible_when_seer_rank_allowed() -> None:
    assert _visible("rank_help", allowed_features=("seer_rank",))


def test_messaging_visibility_reads_app_config() -> None:
    assert _visible(
        "messaging",
        allowed_features=("text",),
        config=_config(
            group_actions=[StubMessageAction(enabled=True, feature="text")]
        ),
    )


def test_ai_intent_visibility_requires_key_and_feature() -> None:
    assert _visible(
        "ai_intent",
        allowed_features=("ai_intent",),
        config=_config(ai_intent_enabled=True),
    )
    assert not _visible("team_audit")


def test_team_resource_visibility_reads_app_config() -> None:
    assert _visible(
        "team_resource",
        allowed_features=("team_resource_subscription",),
        config=_config(team_resource_enabled=True),
    )

    assert not _visible(
        "team_resource",
        allowed_features=("team_resource_subscription",),
        config=_config(team_resource_enabled=False),
    )
