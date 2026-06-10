import asyncio
from dataclasses import dataclass

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.custom_plugins.feature_policy import (
    get_superuser_ids,
    groups_for_feature,
)
from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.startup_ready import ensure_startup_ready

from .config import plugin_config

driver = get_driver()


@dataclass(slots=True)
class NoticeState:
    sent: bool = False
    sending: bool = False


_state = NoticeState()


def _get_target_users() -> list[int]:
    return sorted(get_superuser_ids())


def _get_target_groups() -> list[int]:
    return groups_for_feature("admin_notice")


@driver.on_bot_connect
async def send_startup_notice(bot: Bot) -> None:
    if (
        _state.sent
        or _state.sending
        or not plugin_config.startup_config.enabled
    ):
        return

    _state.sending = True

    try:
        target_users = _get_target_users()
        target_groups = _get_target_groups()
        if not target_users and not target_groups:
            logger.warning("startup notice has no admin notice targets")
            return

        await ensure_startup_ready(bot)

        if plugin_config.startup_config.delay > 0:
            await asyncio.sleep(plugin_config.startup_config.delay)

        summary = await send_broadcast_message(
            Message(plugin_config.startup_config.message),
            private_user_ids=target_users,
            group_ids=target_groups,
            bot=bot,
            action_name="startup notice",
            interval_seconds=1.2,
        )

        if summary.succeeded:
            _state.sent = True
            logger.info(f"startup notice sent to {len(summary.succeeded)} users")

    finally:
        if not _state.sent:
            _state.sending = False
