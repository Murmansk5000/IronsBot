from pathlib import Path

from nonebot import get_driver

from ironsbot.config import AppConfig, get_app_config, load_secrets_config
from ironsbot.config.models.message import SendpicBehaviorConfig
from ironsbot.shared.config.config import (
    DEFAULT_SENDPIC_MESSAGE_TEMPLATE,
    PicConfig,
    SendpicBackendType,
)

BackendType = SendpicBackendType
Config = AppConfig
DEFAULT_MESSAGE_TEMPLATE = DEFAULT_SENDPIC_MESSAGE_TEMPLATE
SendpicConfig = SendpicBehaviorConfig


def get_sendpic_config() -> SendpicBehaviorConfig:
    return get_app_config().message.sendpic


def get_sendpic_cnb_token() -> str | None:
    token = load_secrets_config().sendpic_cnb_token
    if token:
        return token

    try:
        raw_token = getattr(get_driver().config, "sendpic_cnb_token", None)
    except ValueError:
        return None

    if raw_token is None:
        return None
    return str(raw_token).strip() or None


def get_sendpic_cnb_repo() -> str | None:
    return get_sendpic_config().cnb_repo


def get_sendpic_local_root() -> Path:
    return get_sendpic_config().local_root


__all__ = [
    "DEFAULT_MESSAGE_TEMPLATE",
    "BackendType",
    "Config",
    "PicConfig",
    "SendpicConfig",
    "get_sendpic_cnb_repo",
    "get_sendpic_cnb_token",
    "get_sendpic_config",
    "get_sendpic_local_root",
]
