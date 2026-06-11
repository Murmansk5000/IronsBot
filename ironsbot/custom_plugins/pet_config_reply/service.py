from collections.abc import Sequence

PET_CONFIG_UNSUPPORTED_MESSAGE = (
    "此机器人暂不支持查询精灵配置。可以发送“帮助”查看目前可用的功能。"
)


def should_reply_pet_config(arg: str, pets: Sequence[object]) -> bool:
    return bool(arg) and not arg.isdigit() and bool(pets)
