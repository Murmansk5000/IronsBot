import os
from pathlib import Path

import nonebot
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.features import Feature
from ironsbot.plugins.help import visibility
from tests.helpers.config import StubMessageAction, stub_app_config
from tests.helpers.onebot_events import group_message_event
from tests.helpers.plugin_registry import build_test_plugin_registry

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


def test_always_visible_help_is_shown() -> None:
    assert visibility.plugin_visible_for_event(
        DEFINITIONS["help"],
        _group_event(),
    )


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


def test_feature_visibility_uses_feature_service(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "seer",
    )

    assert visibility.plugin_visible_for_event(
        DEFINITIONS["seer_query"],
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        DEFINITIONS["rank_help"],
        _group_event(),
    )


def test_seer_query_visible_when_any_seer_subfeature_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "seer_pet",
    )

    assert visibility.plugin_visible_for_event(
        DEFINITIONS["seer_query"],
        _group_event(),
    )


def test_rank_help_visible_when_seer_rank_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "seer_rank",
    )

    assert visibility.plugin_visible_for_event(
        DEFINITIONS["rank_help"],
        _group_event(),
    )


def test_messaging_visibility_reads_app_config(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(
            group_actions=[StubMessageAction(enabled=True, feature="text")]
        ),
    )
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "text",
    )

    assert visibility.plugin_visible_for_event(
        DEFINITIONS["messaging"],
        _group_event(),
    )


def test_ai_intent_visibility_requires_key_and_feature(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "_ai_key_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(ai_intent_enabled=True),
    )
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "ai_intent",
    )

    assert visibility.plugin_visible_for_event(
        DEFINITIONS["ai_intent"],
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        DEFINITIONS["team_audit"],
        _group_event(),
    )


def test_team_resource_visibility_reads_app_config(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(team_resource_enabled=True),
    )
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "team_resource_subscription",
    )

    assert visibility.plugin_visible_for_event(
        DEFINITIONS["team_resource"],
        _group_event(),
    )

    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(team_resource_enabled=False),
    )
    assert not visibility.plugin_visible_for_event(
        DEFINITIONS["team_resource"],
        _group_event(),
    )
