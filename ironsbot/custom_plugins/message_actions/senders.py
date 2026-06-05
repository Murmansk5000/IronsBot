import asyncio
from collections.abc import Iterable

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from .reply_limits import limit_message_by_reply_lines
from .targets import (
    MessageTarget,
    SendSummary,
    TargetSendSummary,
    broadcast_targets,
    group_targets,
    private_targets,
)
from .text import build_message


def get_bot_or_none() -> Bot | None:
    try:
        return get_bot()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"message action failed to get bot: {e}")
        return None


async def send_target_messages(
    targets: Iterable[MessageTarget],
    message: str | Message,
    *,
    bot: Bot | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
) -> TargetSendSummary:
    deduped_targets = list(dict.fromkeys(targets))
    bot = bot or get_bot_or_none()
    if not bot:
        return TargetSendSummary([], deduped_targets)

    succeeded: list[MessageTarget] = []
    failed: list[MessageTarget] = []

    for target in deduped_targets:
        limited_message = limit_message_by_reply_lines(
            message,
            group_id=(
                target.target_id
                if target.target_type == "group"
                else None
            ),
        )
        rendered_message = build_message(
            limited_message,
            at_user_ids=(
                target.at_user_ids
                if target.target_type == "group"
                else ()
            ),
        )

        try:
            if target.target_type == "private":
                await bot.send_private_msg(
                    user_id=target.target_id,
                    message=rendered_message,
                )
            else:
                await bot.send_group_msg(
                    group_id=target.target_id,
                    message=rendered_message,
                )

            logger.info(
                f"{action_name} sent to {target.target_type} {target.target_id}"
            )
            succeeded.append(target)
            await asyncio.sleep(interval_seconds)
        except Exception as e:  # noqa: BLE001
            failed.append(target)
            logger.warning(
                f"{action_name} failed to send to {target.target_type} "
                f"{target.target_id}: {e}"
            )

    return TargetSendSummary(succeeded, failed)


async def send_broadcast_message(  # noqa: PLR0913
    message: str | Message,
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
    bot: Bot | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
) -> TargetSendSummary:
    return await send_target_messages(
        broadcast_targets(
            private_user_ids=private_user_ids,
            group_ids=group_ids,
            group_at_user_ids=group_at_user_ids,
        ),
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
    )


async def send_private_messages(
    user_ids: Iterable[int],
    message: str | Message,
    *,
    bot: Bot | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
) -> SendSummary:
    summary = await send_target_messages(
        private_targets(user_ids),
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
    )
    return SendSummary(
        [target.target_id for target in summary.succeeded],
        [target.target_id for target in summary.failed],
    )


async def send_group_messages(  # noqa: PLR0913
    group_ids: Iterable[int],
    message: str | Message,
    *,
    bot: Bot | None = None,
    at_user_ids: Iterable[int] = (),
    action_name: str = "message action",
    interval_seconds: float = 1.5,
) -> SendSummary:
    summary = await send_target_messages(
        group_targets(group_ids, at_user_ids=at_user_ids),
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
    )
    return SendSummary(
        [target.target_id for target in summary.succeeded],
        [target.target_id for target in summary.failed],
    )
