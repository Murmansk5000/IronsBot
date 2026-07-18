from ironsbot.config.loader import get_app_config
from ironsbot.config.models.message import MessageConfig


def get_message_config() -> MessageConfig:
    return get_app_config().message
