from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.help_visibility import feature_help_visible

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService


def plugin_contribution(
    *,
    settings: Settings,
    features: FeatureService,
    startup_check: Callable[[], Awaitable[None]],
) -> PluginContribution:
    """Declare AI-chat command visibility and startup checks."""

    enabled = settings.ai.enabled
    return PluginContribution(
        id="ai_chat",
        features=frozenset({Feature.AI_CHAT, Feature.ADMIN_NOTICE}),
        help=HelpEntry(
            name="AI聊天",
            description="接入 OpenAI-compatible API 的自定义聊天插件",
            group="ai",
            order=10,
            visible=partial(
                feature_help_visible,
                features=features,
                feature="ai_chat",
                enabled=enabled,
            ),
        ),
        commands=ai_chat_command_contracts(enabled=enabled),
        hooks=(
            PluginHooks(
                first_bot_connect=(("ai_api_check", lambda _bot: startup_check()),)
            )
            if enabled
            else PluginHooks()
        ),
    )
