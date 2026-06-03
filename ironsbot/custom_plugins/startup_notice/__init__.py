import asyncio

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.startup_ready import ensure_startup_ready
from ironsbot.custom_plugins.superuser_policy import get_superuser_ids

from .config import plugin_config

driver = get_driver()
_notice_sent = False
_notice_sending = False


def _get_target_users() -> list[int]:
    return sorted(get_superuser_ids())


@driver.on_bot_connect
async def send_startup_notice(bot: Bot) -> None:
    global _notice_sent, _notice_sending

    if (
        _notice_sent
        or _notice_sending
        or not plugin_config.startup_notice
    ):
        return

    _notice_sending = True

    try:
        target_users = _get_target_users()
        if not target_users:
            logger.warning("startup notice has no target users")
            return

        await ensure_startup_ready(bot)

        if plugin_config.startup_delay > 0:
            await asyncio.sleep(plugin_config.startup_delay)

        summary = await send_broadcast_message(
            Message(plugin_config.startup_message),
            private_user_ids=target_users,
            bot=bot,
            action_name="startup notice",
            interval_seconds=1.2,
        )

        if summary.succeeded:
            _notice_sent = True
            logger.info(f"startup notice sent to {len(summary.succeeded)} users")

    finally:
        if not _notice_sent:
            _notice_sending = False
