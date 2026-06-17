from collections.abc import Sequence

from ironsbot.shared.help_hints import unsupported_feature_help_message

PET_CONFIG_UNSUPPORTED_MESSAGE = unsupported_feature_help_message("查询精灵配置")


def should_reply_pet_config(arg: str, pets: Sequence[object]) -> bool:
    return bool(arg) and not arg.isdigit() and bool(pets)
