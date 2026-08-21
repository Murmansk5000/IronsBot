# SPDX-License-Identifier: MIT
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from nonebot_plugin_saa import (
    MessageFactory,
    PlatformTarget,
    TargetQQGroup,
    TargetQQPrivate,
)
from pydantic import BaseModel, model_validator
from sqlmodel import Field, SQLModel
from typing_extensions import Self


class Topic(SQLModel, table=True):
    """推送主题：订阅与推送的基本单位。"""

    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    allow_subscribe: bool = True
    enabled: bool = True
    created_at: float


class Subscription(SQLModel, table=True):
    """一个目标对一个主题的订阅。target 为目标序列化后的 JSON 字符串。"""

    topic_id: str = Field(primary_key=True, foreign_key="topic.id")
    target: str = Field(primary_key=True)
    target_type: str
    target_key: str
    subscribed_at: float


class PushRecord(SQLModel, table=True):
    """一次推送的发送记录（用于去重与审计）。"""

    id: int | None = Field(default=None, primary_key=True)
    topic_id: str | None = None
    target: str
    dedup_key: str | None = None
    content_preview: str
    ok: bool
    error: str | None = None
    created_at: float


class Schedule(BaseModel):
    """定时推送的调度配置，映射到 APScheduler 的触发器。"""

    type: Literal["interval", "cron", "date"] = "interval"
    # interval 触发器参数（至少设置一个 > 0）
    minutes: float = 0
    hours: float = 0
    seconds: float = 0
    # cron 触发器参数，如 "0 8 * * *"
    cron: str | None = None
    # date 触发器参数
    run_date: datetime | None = None
    timezone: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.type == "interval" and not (self.minutes or self.hours or self.seconds):
            raise ValueError(  # noqa: TRY003
                "interval 类型至少需要设置一个大于 0 的间隔"
            )
        if self.type == "cron" and not self.cron:
            raise ValueError("cron 类型需要设置 cron 表达式")  # noqa: TRY003
        if self.type == "date" and self.run_date is None:
            raise ValueError("date 类型需要设置 run_date")  # noqa: TRY003
        return self


@dataclass(slots=True)
class SendReport:
    """一次推送的汇总结果。"""

    ok_count: int = 0
    fail_count: int = 0
    skipped: bool = False
    failed_targets: list[PlatformTarget] = field(default_factory=list)


#: 定时推送内容提供器：返回 None 表示本次内容无变化、不推送
ContentProvider = Callable[[], Awaitable[MessageFactory | str | None]]


def target_key(target: PlatformTarget) -> str:
    """生成目标的人类可读标识，用于展示与存储。"""
    if isinstance(target, TargetQQGroup):
        return f"群聊:{target.group_id}"
    if isinstance(target, TargetQQPrivate):
        return f"私聊:{target.user_id}"
    return target.platform_type
