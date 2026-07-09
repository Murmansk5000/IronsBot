from ironsbot.integrations.headless_seer.client import client_manager
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.plugins.headless_seer.config import (
    get_headless_config,
    get_headless_credentials,
)

HEADLESS_CONFIG_MISSING_MESSAGE = (
    "未配置 HEADLESS_SEER_USER_ID 或 HEADLESS_SEER_PASSWORD"
)


def headless_user_id_text() -> str:
    return str(get_headless_credentials().headless_seer_user_id or "未配置")


def headless_is_configured() -> bool:
    credentials = get_headless_credentials()
    return (
        credentials.headless_seer_user_id is not None
        and bool(credentials.headless_seer_password)
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

    credentials = get_headless_credentials()
    user_id = credentials.headless_seer_user_id
    password = credentials.headless_seer_password
    if user_id is None or not password:
        raise RuntimeError(HEADLESS_CONFIG_MISSING_MESSAGE)

    headless_config = get_headless_config()
    game = await client_manager.login(
        user_id=user_id,
        password=password,
        login_server_url=headless_config.login_server_addr,
        heartbeat_interval=headless_config.heartbeat_interval,
        reconnect_retries=headless_config.reconnect_retries,
        reconnect_delay=headless_config.reconnect_delay,
        reconnect_delay_max=headless_config.reconnect_delay_max,
    )
    if not game.is_logged_in:
        raise RuntimeError("登录未完成，已进入自动重连")

    return user_id
