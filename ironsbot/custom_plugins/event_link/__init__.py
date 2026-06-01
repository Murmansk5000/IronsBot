import asyncio

from nonebot import get_bot, on_regex, require
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

from .config import Config, plugin_config

__plugin_meta__ = PluginMetadata(
    name="活动链接",
    description="活动链接关键词回复与每日定时推送",
    usage="签到 / 活动 / 链接",
    config=Config,
)

event_link_matcher = on_regex(
    r"^\s*(?:(?:签到|活动|链接)\s*)+$", priority=5, block=True
)


@event_link_matcher.handle()
async def handle_event_link_reply(event: MessageEvent) -> None:
    if isinstance(event, GroupMessageEvent):
        if event.group_id not in plugin_config.event_link_reply_groups:
            return

    elif isinstance(event, PrivateMessageEvent):
        if event.user_id not in plugin_config.event_link_reply_users:
            return

    await event_link_matcher.finish(Message(plugin_config.event_link_text))


@scheduler.scheduled_job(
    "cron",
    hour=plugin_config.event_link_send_hour,
    minute=plugin_config.event_link_send_minute,
    id="daily_send_event_link",
)
async def daily_send_event_link() -> None:
    logger.info("触发每日发送活动链接任务...")

    try:
        bot = get_bot()

        for group_id in plugin_config.event_link_send_groups:
            try:
                await bot.send_group_msg(
                    group_id=group_id,
                    message=plugin_config.event_link_text,
                )
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning(f"群 {group_id} 发送活动链接失败: {e}")

        for user_id in plugin_config.event_link_send_users:
            try:
                await bot.send_private_msg(
                    user_id=user_id,
                    message=plugin_config.event_link_text,
                )
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning(f"用户 {user_id} 发送活动链接失败: {e}")

        logger.info("每日发送活动链接任务执行完成。")

    except Exception as e:
        logger.error(f"每日发送活动链接任务发生异常: {e}")
