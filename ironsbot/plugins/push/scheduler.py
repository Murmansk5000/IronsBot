# SPDX-License-Identifier: MIT
from nonebot import require

require("nonebot_plugin_apscheduler")

from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from .models import ContentProvider, Schedule


def setup_topic_schedule(
    topic_id: str,
    schedule: Schedule,
    provider: ContentProvider,
) -> None:
    """为主题注册定时推送任务（job id 固定，重复注册自动替换）。

    每次触发时调用 provider，返回 ``None`` 表示内容无变化、本次不推送；
    否则将内容推送给该主题的全部订阅者（带去重 key 防止重复）。
    """
    job_id = f"push_topic_{topic_id}"

    if schedule.type == "interval":
        scheduler.add_job(
            _run_scheduled,
            "interval",
            args=[topic_id, provider],
            minutes=schedule.minutes or None,
            hours=schedule.hours or None,
            seconds=schedule.seconds or None,
            id=job_id,
            replace_existing=True,
        )
    elif schedule.type == "cron":
        scheduler.add_job(
            _run_scheduled,
            "cron",
            args=[topic_id, provider],
            cron=schedule.cron,
            timezone=schedule.timezone,
            id=job_id,
            replace_existing=True,
        )
    else:
        scheduler.add_job(
            _run_scheduled,
            "date",
            args=[topic_id, provider],
            run_date=schedule.run_date,
            timezone=schedule.timezone,
            id=job_id,
            replace_existing=True,
        )

    logger.debug(f"已为主题 '{topic_id}' 注册定时推送任务")


async def _run_scheduled(topic_id: str, provider: ContentProvider) -> None:
    from .service import send_to_topic  # 延迟导入避免循环依赖

    try:
        content = await provider()
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error(f"主题 '{topic_id}' 的定时内容提供器执行失败")
        return

    if content is None:
        return

    try:
        report = await send_to_topic(
            topic_id, content, dedup_key=f"scheduled:{topic_id}"
        )
        if report.fail_count:
            logger.warning(
                f"主题 '{topic_id}' 定时推送部分失败：成功 {report.ok_count}，"
                f"失败 {report.fail_count}"
            )
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error(f"主题 '{topic_id}' 定时推送失败")
