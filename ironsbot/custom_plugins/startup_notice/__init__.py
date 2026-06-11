import asyncio

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.startup_ready import ensure_startup_ready

from .config import get_startup_config
from .service import StartupNoticeService

driver = get_driver()

startup_notice_service = StartupNoticeService()


@driver.on_bot_connect
async def send_startup_notice(bot: Bot) -> None:
    config = get_startup_config()
    if not startup_notice_service.should_send(config):
        return

    startup_notice_service.begin_send()

    try:
        targets = startup_notice_service.get_targets()
        if targets.is_empty:
            logger.warning("startup notice has no admin notice targets")
            return

        await ensure_startup_ready(bot)

        if config.delay > 0:
            await asyncio.sleep(config.delay)

        summary = await send_broadcast_message(
            Message(config.message),
            private_user_ids=targets.private_user_ids,
            group_ids=targets.group_ids,
            bot=bot,
            action_name="startup notice",
            interval_seconds=1.2,
        )

        startup_notice_service.mark_result(summary.succeeded)
        if startup_notice_service.state.sent:
            logger.info(f"startup notice sent to {len(summary.succeeded)} users")

    finally:
        startup_notice_service.finish_send()
