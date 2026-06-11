from collections.abc import Iterable

from nonebot.adapters.onebot.v11 import Bot, Message

from ironsbot.shared.messaging import senders as shared_senders
from ironsbot.shared.messaging.targets import (
    MessageTarget,
    TargetSendSummary,
)

from .reply_limits import limit_message_by_reply_lines

get_bot_or_none = shared_senders.get_bot_or_none


def _limit_message_for_target(
    message: str | Message,
    group_id: int | None,
) -> str | Message:
    return limit_message_by_reply_lines(message, group_id=group_id)


async def send_target_messages(
    targets: Iterable[MessageTarget],
    message: str | Message,
    *,
    bot: Bot | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
) -> TargetSendSummary:
    return await shared_senders.send_target_messages(
        targets,
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
        message_limiter=_limit_message_for_target,
    )


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
    return await shared_senders.send_broadcast_message(
        message,
        private_user_ids=private_user_ids,
        group_ids=group_ids,
        group_at_user_ids=group_at_user_ids,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
        message_limiter=_limit_message_for_target,
    )
