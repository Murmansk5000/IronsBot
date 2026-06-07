import time

from nonebot import get_driver
from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.superuser_policy import get_superuser_ids

SUPERUSER_NOTICE_COOLDOWN_SECONDS = 10 * 60
_LAST_SUPERUSER_NOTICE_AT: dict[str, float] = {}


def _get_first_bot():
    bots = get_driver().bots
    if not bots:
        return None

    return next(iter(bots.values()))


async def _send_private_to_superusers(message: str) -> None:
    superuser_uids = get_superuser_ids()
    if not superuser_uids:
        logger.warning("AI chat has no superusers for error notice")
        return

    await send_broadcast_message(
        message,
        private_user_ids=sorted(superuser_uids),
        bot=_get_first_bot(),
        action_name="AI chat error notice",
    )


async def notify_superusers_once(key: str, message: str) -> None:
    if key == "missing_api_key":
        return

    now = time.time()
    last_notice_at = _LAST_SUPERUSER_NOTICE_AT.get(key, 0.0)
    if now - last_notice_at < SUPERUSER_NOTICE_COOLDOWN_SECONDS:
        return

    _LAST_SUPERUSER_NOTICE_AT[key] = now
    await _send_private_to_superusers(message)
