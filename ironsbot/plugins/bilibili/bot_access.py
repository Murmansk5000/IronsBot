from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot


def get_first_bot() -> Bot | None:
    bots = get_driver().bots
    if not bots:
        return None

    return next(iter(bots.values()))
