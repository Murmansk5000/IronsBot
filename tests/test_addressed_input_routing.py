from ironsbot.config.models.features import FeatureConfig
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.plugins.onebot.help.hint import (
    _should_offer_non_ai_group_hint,
)
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime


def _commands() -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="seer_query",
                commands=seer_command_contracts(
                    PlayerIdResolver(
                        lambda _reference, _conversation: None,
                        lambda _actor: None,
                    )
                ),
            ),
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True),
            ),
        ),
        known_features=tuple(feature.value for feature in Feature),
    )
    return catalog


def _features(*, ai_allowed: bool) -> FeatureService:
    runtime = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={"456": ["ai_chat"]} if ai_allowed else {},
            superuser_bypass=False,
        )
    )
    return runtime.features


def test_config_mention_is_not_offered_hint_when_ai_is_allowed() -> None:
    commands = _commands()
    assert not _should_offer_non_ai_group_hint(
        AiInputRoutingService(_features(ai_allowed=True), commands),
        group_message_event("@bot 谱尼配置", to_me=True),
    )


def test_plain_mention_is_not_offered_hint_when_ai_is_allowed() -> None:
    commands = _commands()
    assert not _should_offer_non_ai_group_hint(
        AiInputRoutingService(_features(ai_allowed=True), commands),
        group_message_event("@bot 谱尼强吗", to_me=True),
    )


def test_foreign_mention_is_not_offered_hint() -> None:
    commands = _commands()
    assert not _should_offer_non_ai_group_hint(
        AiInputRoutingService(_features(ai_allowed=False), commands),
        group_message_event("@someone 帮助"),
    )


def test_plain_mention_is_offered_hint_when_ai_is_not_allowed() -> None:
    commands = _commands()
    assert _should_offer_non_ai_group_hint(
        AiInputRoutingService(_features(ai_allowed=False), commands),
        group_message_event("@bot 不会处理", to_me=True),
    )


def test_known_command_is_not_offered_as_fallback_hint() -> None:
    commands = _commands()
    assert not _should_offer_non_ai_group_hint(
        AiInputRoutingService(_features(ai_allowed=False), commands),
        group_message_event("米米号123456789", to_me=True),
    )


def test_blacklisted_actor_is_not_offered_fallback_hint() -> None:
    runtime = build_test_runtime(
        feature_config=FeatureConfig(user_policy={"123": ["blacklist"]})
    )

    commands = _commands()
    assert not _should_offer_non_ai_group_hint(
        AiInputRoutingService(runtime.features, commands),
        group_message_event("不会处理", user_id=123, to_me=True),
    )
