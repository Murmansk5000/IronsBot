from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import nested_json_config
from ironsbot.custom_plugins.common.time_config import (
    normalized_daily_time_csv,
    normalized_daily_times,
)

INVALID_RECONNECT_TIME_ERROR = (
    "HEADLESS_NOTICE_CONFIG.reconnect_check_times must contain daily HH:MM times, "
    'for example "00:01,00:02" or ["00:01","00:02"]'
)


class HeadlessNoticeConfig(BaseModel):
    login_notice: bool = True
    login_notice_message: str = (
        "无头米米号登录未成功。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "依赖米米号登录的功能可能不可用；请检查账号、MD5密码、网络或赛尔号服务器状态。"
    )
    state_notice: bool = True
    state_offline_message: str = (
        "无头米米号已掉线。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "来源：{source}"
    )
    state_online_message: str = (
        "无头米米号已恢复登录。\n"
        "米米号：{user_id}\n"
        "来源：{source}"
    )
    reconnect_check_times: str = "00:01,00:02"

    @field_validator("reconnect_check_times", mode="before")
    @classmethod
    def normalize_reconnect_times(cls, value: object) -> str:
        return normalized_daily_time_csv(
            value,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )

    @property
    def parsed_reconnect_check_times(self) -> list[str]:
        return normalized_daily_times(
            self.reconnect_check_times,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )


class Config(BaseModel):
    headless_notice_config: HeadlessNoticeConfig = Field(
        default_factory=HeadlessNoticeConfig
    )

    @field_validator("headless_notice_config", mode="before")
    @classmethod
    def normalize_notice_config(cls, value: object) -> object:
        return nested_json_config(
            value,
            HeadlessNoticeConfig,
            name="HEADLESS_NOTICE_CONFIG",
        )


plugin_config = get_plugin_config(Config)
