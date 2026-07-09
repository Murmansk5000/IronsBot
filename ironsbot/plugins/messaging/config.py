from ironsbot.config.loader import get_app_config
from ironsbot.config.models.message import (
    ENABLED_COMMANDS_REQUIRED_ERROR,
    BaseMessageAction,
    CommandMessageAction,
    GroupCommandMessageAction,
    GroupScheduledMessageAction,
    MessageConfig,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    PushUnsubscribeConfig,
    ScheduledMessageAction,
)


def get_message_config() -> MessageConfig:
    return get_app_config().message


__all__ = [
    "ENABLED_COMMANDS_REQUIRED_ERROR",
    "BaseMessageAction",
    "CommandMessageAction",
    "GroupCommandMessageAction",
    "GroupScheduledMessageAction",
    "PrivateCommandMessageAction",
    "PrivateScheduledMessageAction",
    "PushUnsubscribeConfig",
    "ScheduledMessageAction",
    "get_message_config",
]
