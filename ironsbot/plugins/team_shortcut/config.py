from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.seer import TeamShortcutConfig

Config = AppConfig
TeamConfig = TeamShortcutConfig


def get_team_shortcut_config() -> TeamShortcutConfig:
    return get_app_config().seer.team_shortcut


def get_team_ids() -> list[int]:
    return get_team_shortcut_config().team_ids


def get_team_resource_users() -> list[int]:
    return get_team_shortcut_config().resource_users

__all__ = [
    "Config",
    "TeamConfig",
    "TeamShortcutConfig",
    "get_team_ids",
    "get_team_resource_users",
    "get_team_shortcut_config",
]
