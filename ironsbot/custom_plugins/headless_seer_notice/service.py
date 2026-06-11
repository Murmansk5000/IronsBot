from ironsbot.plugins.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.plugins.headless_seer.manager import client_manager
from ironsbot.shared.config.config import get_shared_config

HEADLESS_CONFIG_MISSING_MESSAGE = (
    "未配置 HEADLESS_SEER_USER_ID 或 HEADLESS_SEER_PASSWORD"
)

shared_config = get_shared_config()


def headless_user_id_text() -> str:
    return str(shared_config.headless_seer_user_id or "未配置")


def headless_is_configured() -> bool:
    return (
        shared_config.headless_seer_user_id is not None
        and bool(shared_config.headless_seer_password)
    )


def headless_login_failure_reason() -> str | None:
    try:
        client_manager.get_client()
    except Exception as e:  # noqa: BLE001
        return str(e)

    return None


async def login_headless_client() -> int:
    try:
        game = client_manager.get_client()
        if game.is_logged_in:
            return int(game.user_id)
    except (DisconnectedError, NotLoggedInError):
        client_manager.shutdown()

    user_id = shared_config.headless_seer_user_id
    password = shared_config.headless_seer_password
    if user_id is None or not password:
        raise RuntimeError(HEADLESS_CONFIG_MISSING_MESSAGE)

    game = await client_manager.login(
        user_id=user_id,
        password=password,
        login_server_url=shared_config.headless_seer_login_server_addr,
        heartbeat_interval=shared_config.headless_seer_heartbeat_interval,
        reconnect_retries=shared_config.headless_seer_reconnect_retries,
        reconnect_delay=shared_config.headless_seer_reconnect_delay,
        reconnect_delay_max=shared_config.headless_seer_reconnect_delay_max,
    )
    if not game.is_logged_in:
        raise RuntimeError("登录未完成，已进入自动重连")

    return user_id
