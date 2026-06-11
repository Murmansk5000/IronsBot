from ironsbot.config import get_app_config
from ironsbot.shared.config.config import MeetingConfig


def get_meeting_config() -> MeetingConfig:
    return get_app_config().message.meeting

__all__ = [
    "MeetingConfig",
    "get_meeting_config",
]
