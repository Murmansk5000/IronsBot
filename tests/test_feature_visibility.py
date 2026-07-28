import os
from pathlib import Path

import nonebot

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.messaging import MessageCommandAction
from ironsbot.config.models.settings import Settings
from ironsbot.core.features import Feature, FeatureConfig, FeatureService
from ironsbot.plugins.help.menu import visible_help_entries
from ironsbot.runtime.commands import CommandCatalog
from tests.helpers.onebot_events import group_message_event
from tests.helpers.plugin_registry import build_test_plugin_registry

DEFINITIONS = {
    definition.id: definition
    for definition in build_test_plugin_registry()
}


def _group_event(
    text: str = "帮助",
    *,
    user_id: int = 2,
    role: str = "member",
):
    return group_message_event(
        text,
        user_id=user_id,
        group_id=4,
        sender={"role": role},
    )


def _settings(
    *,
    allowed_features: tuple[str, ...] = (),
    ai_key_configured: bool = True,
    ai_intent_enabled: bool = True,
    team_resource_enabled: bool = True,
    messaging_enabled: bool = False,
) -> Settings:
    settings = Settings(
        features=FeatureConfig(
            group_policy={"4": list(allowed_features)},
            superuser_bypass=False,
        )
    )
    settings.ai.api_key = "test-key" if ai_key_configured else ""
    settings.ai.intent_actions_enabled = ai_intent_enabled
    settings.seer.team_resource.enabled = team_resource_enabled
    if messaging_enabled:
        settings.messaging.commands = [
            MessageCommandAction(
                id="test_message",
                commands=["测试消息"],
                feature="text",
                message="测试回复",
            )
        ]
    return settings


def _visible(
    plugin_id: str,
    *,
    settings: Settings | None = None,
    user_id: int = 2,
    role: str = "member",
) -> bool:
    settings = settings or _settings()
    features = FeatureService(
        settings.features,
        frozenset(settings.bot.superusers),
    )
    definitions = build_test_plugin_registry(settings)
    commands = CommandCatalog()
    commands.load(
        definitions,
        known_features={
            *(feature.value for feature in Feature),
            *features.command_features,
            *features.schedule_features,
        },
    )
    entries = visible_help_entries(
        definitions,
        _group_event(user_id=user_id, role=role),
        features=features,
        commands=commands,
        ignored_plugins=tuple(settings.features.help.ignored_plugins),
    )
    return plugin_id in {entry.key for entry in entries}


def test_always_visible_help_is_shown() -> None:
    assert _visible("help")


def test_plugin_definitions_own_feature_visibility() -> None:
    assert DEFINITIONS["team_audit"].features == frozenset({Feature.TEAM_AUDIT})
    assert DEFINITIONS["team_resource"].features == frozenset(
        {Feature.TEAM_RESOURCE_SUBSCRIPTION}
    )
    assert DEFINITIONS["pet_config"].features == frozenset(
        {Feature.PET_CONFIG}
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
    assert _visible(
        "seer_query",
        settings=_settings(allowed_features=("seer",)),
    )
    assert not _visible("rank_help")


def test_seer_query_visible_when_any_seer_subfeature_allowed() -> None:
    assert _visible(
        "seer_query",
        settings=_settings(allowed_features=("seer_pet",)),
    )


def test_pet_config_visible_when_enabled_for_group() -> None:
    assert _visible(
        "pet_config",
        settings=_settings(allowed_features=("pet_config",)),
    )


def test_pet_config_is_not_enabled_by_seer_bundle() -> None:
    assert not _visible(
        "pet_config",
        settings=_settings(allowed_features=("seer",)),
    )


def test_superuser_group_help_respects_group_feature_policy() -> None:
    settings = _settings()
    settings.features.superuser_bypass = True
    settings.bot.superusers = [2]
    settings.pet_config.enabled = True

    assert not _visible("seer_query", settings=settings)
    assert not _visible("pet_config", settings=settings)
    assert not _visible("headless_notice", settings=settings)


def test_superuser_group_help_includes_enabled_features() -> None:
    settings = _settings(allowed_features=("seer", "pet_config"))
    settings.features.superuser_bypass = True
    settings.bot.superusers = [2]
    settings.pet_config.enabled = True

    assert _visible("seer_query", settings=settings)
    assert _visible("pet_config", settings=settings)


def test_rank_help_visible_when_seer_rank_allowed() -> None:
    assert _visible(
        "rank_help",
        settings=_settings(allowed_features=("seer_rank",)),
    )


def test_help_menu_uses_current_user_command_permissions() -> None:
    settings = _settings(allowed_features=("bili_push",))

    assert not _visible("bilibili", settings=settings)
    assert _visible("bilibili", settings=settings, role="admin")


def test_messaging_visibility_reads_app_config() -> None:
    assert _visible(
        "messaging",
        settings=_settings(
            allowed_features=("text",),
            messaging_enabled=True,
        ),
    )


def test_ai_intent_visibility_requires_key_and_feature() -> None:
    assert _visible(
        "ai_intent",
        settings=_settings(
            allowed_features=("ai_intent",),
            ai_intent_enabled=True,
        ),
    )
    assert not _visible(
        "ai_intent",
        settings=_settings(
            allowed_features=("ai_intent",),
            ai_key_configured=False,
        ),
    )
    assert not _visible("team_audit")


def test_team_resource_visibility_reads_app_config() -> None:
    assert _visible(
        "team_resource",
        settings=_settings(
            allowed_features=("team_resource_subscription",),
            team_resource_enabled=True,
        ),
    )

    assert not _visible(
        "team_resource",
        settings=_settings(
            allowed_features=("team_resource_subscription",),
            team_resource_enabled=False,
        ),
    )
