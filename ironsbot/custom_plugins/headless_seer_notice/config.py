import json
from collections.abc import Sequence

from nonebot import get_plugin_config
from pydantic import BaseModel, field_validator

INVALID_RECONNECT_TIME_ERROR = (
    "headless_reconnect_check_times must contain daily HH:MM times, "
    'for example "00:01,00:02" or ["00:01","00:02"]'
)
RECONNECT_TIME_PARTS = 2
MIN_HOUR = 0
MAX_HOUR = 23
MIN_MINUTE = 0
MAX_MINUTE = 59


def _normalize_reconnect_time(value: object) -> str:
    if not isinstance(value, str):
        value = str(value)

    text = value.strip()
    parts = text.split(":")
    if len(parts) != RECONNECT_TIME_PARTS:
        raise ValueError(INVALID_RECONNECT_TIME_ERROR)

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(INVALID_RECONNECT_TIME_ERROR) from exc

    if not MIN_HOUR <= hour <= MAX_HOUR or not MIN_MINUTE <= minute <= MAX_MINUTE:
        raise ValueError(INVALID_RECONNECT_TIME_ERROR)

    return f"{hour:02d}:{minute:02d}"


def _split_reconnect_times(value: object) -> list[object]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(INVALID_RECONNECT_TIME_ERROR) from exc
            return _split_reconnect_times(parsed)

        return [
            part.strip()
            for part in text.replace("，", ",").replace("；", ",").split(",")
            if part.strip()
        ]

    if isinstance(value, Sequence):
        return list(value)

    return [value]


class Config(BaseModel):
    seer_login_notice: bool = True
    seer_login_notice_message: str = (
        "无头米米号登录未成功。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "依赖米米号登录的功能可能不可用；请检查账号、MD5密码、网络或赛尔号服务器状态。"
    )
    headless_state_notice: bool = True
    headless_state_offline_message: str = (
        "无头米米号已掉线。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "来源：{source}"
    )
    headless_state_online_message: str = (
        "无头米米号已恢复登录。\n"
        "米米号：{user_id}\n"
        "来源：{source}"
    )
    headless_reconnect_check_times: str = "00:01,00:02"

    @field_validator("headless_reconnect_check_times", mode="before")
    @classmethod
    def normalize_reconnect_times(cls, value: object) -> str:
        times = [
            _normalize_reconnect_time(item)
            for item in _split_reconnect_times(value)
        ]
        return ",".join(sorted(dict.fromkeys(times)))

    @property
    def parsed_reconnect_check_times(self) -> list[str]:
        return [
            _normalize_reconnect_time(item)
            for item in _split_reconnect_times(self.headless_reconnect_check_times)
        ]


plugin_config = get_plugin_config(Config)
