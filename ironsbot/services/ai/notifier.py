import time

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.config.loader import get_app_config
from ironsbot.shared.features import (
    get_superuser_ids,
    groups_for_feature,
)
from ironsbot.shared.messaging import send_broadcast_message

_LAST_SUPERUSER_NOTICE_AT: dict[str, float] = {}


def _get_first_bot() -> Bot | None:
    bots = get_driver().bots
    if not bots:
        return None

    bot = next(iter(bots.values()))
    return bot if isinstance(bot, Bot) else None


async def _send_admin_notice(
    message: str,
    *,
    subscription_key: str,
    action_name: str,
) -> None:
    superuser_uids = get_superuser_ids()
    group_ids = groups_for_feature("admin_notice")
    if not superuser_uids and not group_ids:
        logger.warning("AI chat has no admin notice targets")
        return

    await send_broadcast_message(
        message,
        private_user_ids=sorted(superuser_uids),
        group_ids=group_ids,
        bot=_get_first_bot(),
        action_name=action_name,
        subscription_key=subscription_key,
    )


async def notify_superusers_once(
    key: str,
    message: str,
    *,
    subscription_key: str = "admin_notice",
    action_name: str = "admin notice",
) -> None:
    now = time.time()
    last_notice_at = _LAST_SUPERUSER_NOTICE_AT.get(key, 0.0)
    if now - last_notice_at < get_app_config().ai.admin_notice_cooldown_seconds:
        return

    _LAST_SUPERUSER_NOTICE_AT[key] = now
    await _send_admin_notice(
        message,
        subscription_key=subscription_key,
        action_name=action_name,
    )
