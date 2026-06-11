from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.message import (
    ENABLED_COMMANDS_REQUIRED_ERROR,
    BaseMessageAction,
    CommandMessageAction,
    GroupCommandMessageAction,
    GroupScheduledMessageAction,
    MessageConfig,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    ReplyLineConfig,
    ScheduledMessageAction,
)

Config = AppConfig
MessageActionsConfig = MessageConfig


def get_message_config() -> MessageConfig:
    return get_app_config().message


def get_reply_config() -> ReplyLineConfig:
    return get_message_config().reply

__all__ = [
    "ENABLED_COMMANDS_REQUIRED_ERROR",
    "BaseMessageAction",
    "CommandMessageAction",
    "Config",
    "GroupCommandMessageAction",
    "GroupScheduledMessageAction",
    "MessageActionsConfig",
    "PrivateCommandMessageAction",
    "PrivateScheduledMessageAction",
    "ReplyLineConfig",
    "ScheduledMessageAction",
    "get_message_config",
    "get_reply_config",
]
