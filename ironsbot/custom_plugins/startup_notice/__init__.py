import asyncio

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from .config import plugin_config

driver = get_driver()
_notice_sent = False
_notice_sending = False


def _get_target_users() -> list[int]:
    users = set(plugin_config.startup_notice_users)

    superusers = getattr(
        driver.config,
        "superusers",
        set(),
    )

    for user_id in superusers:
        try:
            users.add(int(user_id))
        except (TypeError, ValueError):
            continue

    return sorted(users)


async def _wait_for_startup_services() -> None:
    try:
        from ironsbot.custom_plugins.bilibili_monitor import wait_startup_check_done
    except Exception as e:
        logger.warning(f"启动通知等待服务状态失败，将直接发送: {e}")
        return

    await wait_startup_check_done()


@driver.on_bot_connect
async def send_startup_notice(bot: Bot) -> None:
    global _notice_sent, _notice_sending

    if (
        _notice_sent
        or _notice_sending
        or not plugin_config.startup_notice_enabled
    ):
        return

    _notice_sending = True

    try:
        target_users = _get_target_users()
        if not target_users:
            logger.warning("启动通知未配置接收用户，跳过发送")
            return

        await _wait_for_startup_services()

        if plugin_config.startup_notice_delay_seconds > 0:
            await asyncio.sleep(plugin_config.startup_notice_delay_seconds)

        message = Message(plugin_config.startup_notice_message)

        sent_any = False
        for user_id in target_users:
            try:
                await bot.send_private_msg(user_id=user_id, message=message)
                sent_any = True
                await asyncio.sleep(1.2)
            except Exception as e:
                logger.warning(f"启动通知发送失败 {user_id}: {e}")

        if sent_any:
            _notice_sent = True
            logger.info(f"启动通知已发送给 {len(target_users)} 个用户")

    finally:
        if not _notice_sent:
            _notice_sending = False
