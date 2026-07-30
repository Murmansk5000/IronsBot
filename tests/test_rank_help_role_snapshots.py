from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.config.models.settings import Settings
from ironsbot.core.features import Feature, FeatureConfig, FeatureService
from ironsbot.plugins.help.menu import entry_from_definition, format_plugin_detail
from ironsbot.runtime.commands import CommandCatalog
from ironsbot.runtime.onebot_context import command_context
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.plugin_registry import build_test_plugin_registry

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent


_REGULAR_RANK_COMMANDS = (
    "rank.help",
    "rank.global_collection",
    "rank.global_peak",
    "rank.sample_collection",
    "rank.sample_peak",
)
_GROUP_MANAGER_RANK_COMMANDS = (*_REGULAR_RANK_COMMANDS, "rank.display_limit")
_SUPERUSER_RANK_COMMANDS = (
    *_GROUP_MANAGER_RANK_COMMANDS,
    "rank.sample_status",
    "rank.sample_refresh",
    "rank.page_status",
    "rank.page_refresh",
    "rank.page_batch",
)


def _settings() -> Settings:
    settings = Settings(
        features=FeatureConfig(
            group_policy={"4": ["seer_rank"]},
            user_policy={"1": ["seer_rank"]},
            superuser_bypass=True,
        )
    )
    settings.bot.superusers = ["3"]
    return settings


def _rank_command_ids(event: MessageEvent) -> tuple[str, ...]:
    settings = _settings()
    definitions = build_test_plugin_registry(settings)
    features = FeatureService(settings.features, settings.superuser_ids)
    catalog = CommandCatalog()
    catalog.load(
        definitions,
        known_features={feature.value for feature in Feature},
    )
    return tuple(
        command.id
        for command in catalog.available_for_context(
            command_context(event),
            features,
            plugin_id="rank_help",
        )
    )


def test_rank_help_command_visibility_role_snapshots() -> None:
    assert _rank_command_ids(group_message_event(user_id=1, group_id=4)) == (
        _REGULAR_RANK_COMMANDS
    )
    assert _rank_command_ids(
        group_message_event(user_id=2, group_id=4, sender={"role": "admin"})
    ) == _GROUP_MANAGER_RANK_COMMANDS
    assert _rank_command_ids(group_message_event(user_id=3, group_id=4)) == (
        _SUPERUSER_RANK_COMMANDS
    )
    assert _rank_command_ids(private_message_event(user_id=1)) == _REGULAR_RANK_COMMANDS


def test_rank_help_group_manager_detail_only_shows_group_setting() -> None:
    settings = _settings()
    definitions = build_test_plugin_registry(settings)
    features = FeatureService(settings.features, settings.superuser_ids)
    catalog = CommandCatalog()
    catalog.load(definitions, known_features={feature.value for feature in Feature})
    definition = next(
        definition for definition in definitions if definition.id == "rank_help"
    )
    entry = entry_from_definition(definition)

    detail = format_plugin_detail(
        entry,
        group_message_event(user_id=2, group_id=4, sender={"role": "admin"}),
        features,
        catalog,
        ignored_plugins=(),
    )

    assert "/榜单显示 20" in detail
    assert "/样本情况" not in detail
