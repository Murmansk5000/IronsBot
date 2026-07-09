# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import get_driver

from ironsbot.config.loader import get_app_config, load_credentials_config
from ironsbot.config.models.runtime import HeadlessConfig
from ironsbot.config.models.secrets import CredentialsConfig


def get_headless_config() -> HeadlessConfig:
    return get_app_config().runtime.headless


def _driver_credentials_data() -> dict[str, object]:
    try:
        driver_config = get_driver().config
    except ValueError:
        return {}

    data: dict[str, object] = {}
    user_id = getattr(driver_config, "headless_seer_user_id", None)
    password = getattr(driver_config, "headless_seer_password", None)
    if user_id not in (None, ""):
        data["headless_seer_user_id"] = user_id
    if password not in (None, ""):
        data["headless_seer_password"] = password
    return data


def get_headless_credentials() -> CredentialsConfig:
    data = load_credentials_config().model_dump()
    for key, value in _driver_credentials_data().items():
        if data.get(key) in (None, ""):
            data[key] = value
    return CredentialsConfig.model_validate(data)

__all__ = [
    "CredentialsConfig",
    "HeadlessConfig",
    "get_headless_config",
    "get_headless_credentials",
]
