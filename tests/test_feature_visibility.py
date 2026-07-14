import os
from pathlib import Path

from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

from ironsbot.plugins.help import visibility
from tests.helpers.config import StubMessageAction, stub_app_config
from tests.helpers.onebot_events import group_message_event


def _group_event(text: str = "帮助"):
    return group_message_event(
        text,
        user_id=2,
        group_id=4,
    )


def _config(
    *,
    ai_intent_enabled: bool = True,
    team_subscriptions: list[object] | None = None,
    group_actions: list[StubMessageAction] | None = None,
):
    return stub_app_config(
        ai_intent_enabled=ai_intent_enabled,
        team_subscriptions=team_subscriptions,
        group_actions=group_actions,
    )


def test_always_visible_help_is_shown() -> None:
    assert visibility.plugin_visible_for_event(
        "帮助",
        "ironsbot.plugins.help",
        _group_event(),
    )


def test_help_visibility_maps_features_to_plugin_modules() -> None:
    assert visibility.features_for_plugin_module(
        "ironsbot.plugins.team_audit_welcome"
    ) == ("team_audit",)
    assert visibility.features_for_plugin_module(
        "ironsbot.plugins.team_resource_subscription"
    ) == ("team_resource_subscription",)
    assert visibility.features_for_plugin_module("ironsbot.plugins.fire_manual_ad") == (
        "fire_manual_ad",
    )
    assert visibility.features_for_plugin_module("ironsbot.plugins.ai_intent") == (
        "ai_intent",
        "ai_intent_team_recommend",
        "ai_intent_fire_manual",
    )


def test_feature_module_visibility_uses_feature_service(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "seer",
    )

    assert visibility.plugin_visible_for_event(
        "赛尔号查询",
        "ironsbot.plugins.seer.query",
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        "榜单",
        "ironsbot.plugins.seer.rank_help",
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
        "赛尔号查询",
        "ironsbot.plugins.seer.query",
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
        "榜单",
        "ironsbot.plugins.seer.rank_help",
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
        "文本发送",
        "ironsbot.plugins.messaging",
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
        "AI意图分析",
        "ironsbot.plugins.ai_intent",
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        "战队审核入群提示",
        "ironsbot.plugins.team_audit_welcome",
        _group_event(),
    )


def test_team_resource_visibility_reads_app_config(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(team_subscriptions=[object()]),
    )
    monkeypatch.setattr(
        visibility,
        "feature_visible_for_help",
        lambda _event, feature: feature == "team_resource_subscription",
    )

    assert visibility.plugin_visible_for_event(
        "战队资源订阅",
        "ironsbot.plugins.team_resource_subscription",
        _group_event(),
    )
