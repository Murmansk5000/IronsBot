# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import MessageFactory
from seerapi_models.build_model import BaseResModel
from sqlmodel import Session

from ironsbot.plugins.seer_data.db import Getter, SeerAPISession
from ironsbot.utils.prompt import (
    PROMPT_STATE_KEY,
    Prompt,
    PromptItem,
)
from ironsbot.utils.prompt import (
    enter_prompt as _enter_prompt,
)

_M = TypeVar("_M", bound=BaseResModel)

__all__ = [
    "PROMPT_STATE_KEY",
    "Prompt",
    "PromptItem",
    "enter_prompt",
    "simple_prompt_resolver",
]


async def enter_prompt(
    matcher: Matcher,
    event: Event,
    state: T_State,
    prompt: "Prompt[Any]",
    resolver: Callable[[Any, Matcher, Session], Awaitable[None]],
) -> None:
    """使用赛尔号数据会话进入通用 Prompt 选择循环。"""
    await _enter_prompt(
        matcher,
        event,
        state,
        prompt,
        resolver,
        session_dependency=SeerAPISession,
    )


def simple_prompt_resolver(
    data_getter: Getter[_M],
    message_builder: Callable[[_M], Awaitable[MessageFactory]],
    entity_name: str,
) -> Callable[..., Awaitable[None]]:
    """为 ``enter_prompt`` 创建简单的解析回调。

    适用于 Prompt 值为数据库主键 ID 的常见场景：
    通过 ``data_getter`` 获取对象，
    再用 ``message_builder`` 构建回复。

    Args:
        data_getter: ``GetData`` 实例，通过
            ``.get(session, id)`` 从数据库获取对象。
        message_builder: 异步函数，将数据库对象构建为
            回复消息。
        entity_name: 实体中文名称，用于错误提示
            （如 ``"刻印"``、``"宠物"``）。
    """

    async def _resolver(
        item: PromptItem[int],
        matcher: Matcher,
        session: Any,
    ) -> None:
        obj = data_getter.get(session, item.value)
        if not obj:
            await matcher.finish(
                message=(
                    f"❌未找到{entity_name} {item.value}（这是一个bug，请反馈给开发者）"
                )
            )
        msg = await message_builder(obj)
        await msg.send()

    return _resolver
