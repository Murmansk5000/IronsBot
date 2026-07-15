import time

from ironsbot.config.loader import get_app_config
from ironsbot.shared.messaging.admin_notice import send_admin_notice

_LAST_SUPERUSER_NOTICE_AT: dict[str, float] = {}


async def notify_superusers_once(
    key: str,
    message: str,
    *,
    subscription_key: str = "admin_notice",
    action_name: str = "admin notice",
) -> None:
    now = time.time()
    last_notice_at = _LAST_SUPERUSER_NOTICE_AT.get(key, 0.0)
    if now - last_notice_at < get_app_config().ai.admin_notice_cooldown_seconds:
        return

    _LAST_SUPERUSER_NOTICE_AT[key] = now
    await send_admin_notice(
        message,
        subscription_key=subscription_key,
        action_name=action_name,
    )
