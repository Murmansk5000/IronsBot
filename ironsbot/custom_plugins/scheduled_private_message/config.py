from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self


class ScheduledPrivateMessageTask(BaseModel):
    id: str = ""
    user_ids: list[int] = Field(default_factory=list)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    message: str
    enabled: bool = True
    day_of_week: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("定时私聊内容不能为空")
        return message

    @model_validator(mode="after")
    def validate_enabled_task(self) -> Self:
        if self.enabled and not self.user_ids:
            raise ValueError("已启用的定时私聊任务必须配置 user_ids")
        return self


class Config(BaseModel):
    scheduled_private_messages: list[ScheduledPrivateMessageTask] = Field(
        default_factory=list
    )


plugin_config = get_plugin_config(Config)
