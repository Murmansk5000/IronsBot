from nonebot import get_driver

from ironsbot.config import AppConfig, get_app_config, load_secrets_config
from ironsbot.config.models.ai import (
    AiActionBase,
    AiActionTemplate,
    AiIntentAction,
    resolve_configured_actions,
)
from ironsbot.config.models.ai import (
    AiConfig as AiIntentConfig,
)
from ironsbot.config.models.seer import TeamShortcutConfig

Config = AppConfig


def get_ai_config() -> AiIntentConfig:
    return get_app_config().ai


def get_ai_key() -> str:
    key = load_secrets_config().ai_key.strip()
    if key:
        return key

    try:
        return str(getattr(get_driver().config, "ai_key", "") or "").strip()
    except ValueError:
        return ""


def get_team_shortcut_config() -> TeamShortcutConfig:
    return get_app_config().seer.team_shortcut


def get_configured_actions() -> list[AiIntentAction]:
    return resolve_configured_actions(get_ai_config())


def get_team_ids() -> list[int]:
    return get_team_shortcut_config().team_ids


def get_team_resource_users() -> list[int]:
    return get_team_shortcut_config().resource_users


__all__ = [
    "AiActionBase",
    "AiActionTemplate",
    "AiIntentAction",
    "AiIntentConfig",
    "Config",
    "get_ai_config",
    "get_ai_key",
    "get_configured_actions",
    "get_team_ids",
    "get_team_resource_users",
    "get_team_shortcut_config",
]
