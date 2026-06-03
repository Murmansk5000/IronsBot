from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.startup_ready import register_startup_check
from ironsbot.custom_plugins.superuser_policy import get_superuser_ids
from ironsbot.plugins.headless_seer.config import plugin_config as headless_config
from ironsbot.plugins.headless_seer.manager import client_manager

from .config import plugin_config


def _headless_is_configured() -> bool:
    return (
        headless_config.headless_seer_user_id is not None
        and bool(headless_config.headless_seer_password)
    )


def _headless_login_failure_reason() -> str | None:
    try:
        client_manager.get_client()
    except Exception as e:  # noqa: BLE001
        return str(e)

    return None


def _build_notice_message(reason: str) -> Message:
    user_id = headless_config.headless_seer_user_id or "未配置"
    return Message(
        plugin_config.headless_seer_login_failure_notice_message.format(
            user_id=user_id,
            reason=reason,
        )
    )


async def _startup_check(bot: Bot) -> None:
    if (
        not plugin_config.headless_seer_login_failure_notice_enabled
        or not _headless_is_configured()
    ):
        return

    reason = _headless_login_failure_reason()
    if reason is None:
        return

    target_users = sorted(get_superuser_ids())
    if not target_users:
        logger.warning("headless seer failure notice has no superusers")
        return

    await send_broadcast_message(
        _build_notice_message(reason),
        private_user_ids=target_users,
        bot=bot,
        action_name="headless seer failure notice",
        interval_seconds=1.2,
    )


register_startup_check("headless_seer_login", _startup_check)
