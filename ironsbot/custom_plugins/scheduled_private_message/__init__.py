import asyncio
import re

from nonebot import get_bot, require
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

from .config import Config, ScheduledPrivateMessageTask, plugin_config

__plugin_meta__ = PluginMetadata(
    name="定时私聊",
    description="按配置定时向指定用户发送私聊消息",
    config=Config,
)


def _job_id(index: int, task: ScheduledPrivateMessageTask) -> str:
    raw_id = task.id or f"task_{index}"
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_id).strip("_")
    return f"scheduled_private_message_{safe_id or index}"


def _message_text(task: ScheduledPrivateMessageTask) -> str:
    return task.message.replace("\\n", "\n")


async def _send_private_message_task(task: ScheduledPrivateMessageTask) -> None:
    try:
        bot = get_bot()
    except Exception as e:
        logger.warning(f"定时私聊任务 {task.id or '<unnamed>'} 获取 Bot 失败: {e}")
        return

    message = Message(_message_text(task))
    for user_id in task.user_ids:
        try:
            await bot.send_private_msg(user_id=user_id, message=message)
            logger.info(f"定时私聊任务 {task.id or '<unnamed>'} 已发送给用户 {user_id}")
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.warning(
                f"定时私聊任务 {task.id or '<unnamed>'} 发送给用户 {user_id} 失败: {e}"
            )


def _register_task(index: int, task: ScheduledPrivateMessageTask) -> None:
    if not task.enabled:
        logger.info(f"定时私聊任务 {task.id or index} 未启用，跳过注册")
        return

    trigger_kwargs: dict[str, int | str] = {
        "hour": task.hour,
        "minute": task.minute,
        "second": 0,
    }
    if task.day_of_week:
        trigger_kwargs["day_of_week"] = task.day_of_week

    scheduler.add_job(
        _send_private_message_task,
        "cron",
        kwargs={"task": task},
        id=_job_id(index, task),
        replace_existing=True,
        **trigger_kwargs,
    )
    logger.info(
        "已注册定时私聊任务 "
        f"{task.id or index}: {task.hour:02d}:{task.minute:02d}, "
        f"{len(task.user_ids)} 个用户"
    )


for _index, _task in enumerate(plugin_config.scheduled_private_messages, start=1):
    _register_task(_index, _task)
