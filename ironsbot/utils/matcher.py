# SPDX-License-Identifier: MIT
"""自定义 Matcher 会话控制工具。

提供 :class:`PromptSessionManager` 管理 prompt 会话版本，
以及 :func:`reject_with_rule` 创建带自定义 Rule 的临时 Matcher。
"""

from typing import TYPE_CHECKING, Any, TypeAlias

from nonebot.consts import REJECT_CACHE_TARGET, REJECT_TARGET
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher, current_bot, current_event, current_handler
from nonebot.rule import Rule

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Event, Message, MessageSegment, MessageTemplate

T_Message: TypeAlias = "str | Message | MessageSegment | MessageTemplate"


class PromptSessionManager:
    """基于版本号的 prompt 会话管理器。

    每个用户（session_id）维护一个递增的版本号。
    创建临时 Matcher 时将版本号嵌入 Rule，
    版本号递增后旧 Rule 自动失效。
    """

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def acquire(self, session_id: str) -> int:
        """分配新版本号，同时使该用户旧版本失效。"""
        v = self._versions.get(session_id, 0) + 1
        self._versions[session_id] = v
        return v

    def invalidate(self, session_id: str) -> None:
        """使当前 session 的 prompt 失效（仅递增版本号）。"""
        self.acquire(session_id)

    def make_rule(
        self,
        session_id: str,
        version: int,
        content_check: "Callable[[Event], bool]",
    ) -> Rule:
        """创建绑定版本号的 Rule。版本不匹配时返回 False。"""
        versions = self._versions

        def _check(event: "Event") -> bool:
            if versions.get(session_id) != version:
                return False
            return content_check(event)

        return Rule(_check)


prompt_session_manager = PromptSessionManager()
"""模块级单例，供全局使用。"""


async def reject_with_rule(
    matcher: "Matcher",
    rule: Rule,
    prompt: "T_Message | None" = None,
    **kwargs: Any,
) -> None:
    """带自定义 Rule 的 reject —— 替代 ``matcher.reject()``。

    标准 ``reject()`` 创建的临时 Matcher 使用空 ``Rule()``，
    会拦截用户的 **所有** 消息。本函数允许指定一个 Rule，
    只有满足该 Rule 的消息才会被临时 Matcher 捕获，
    其余消息（如其他命令）可正常传播。

    内部复刻了 ``Matcher.run()`` 中处理 ``RejectedException`` 的逻辑：

    1. 发送 prompt（可选）
    2. 将当前 handler 重新插回执行队列（等效 ``resolve_reject``）
    3. 调用 ``Matcher.new()`` 创建临时 Matcher，传入自定义 Rule
    4. 抛出 ``FinishedException`` 结束当前执行
       （``run()`` 对 ``FinishedException`` 仅做 ``pass``，不会再创建第二个临时 Matcher）

    Args:
        matcher: 当前 Matcher 实例。
        rule: 临时 Matcher 使用的匹配规则。
        prompt: 发送给用户的提示消息。
        **kwargs: 传递给 ``Matcher.send()`` 的额外参数。

    Raises:
        FinishedException: 始终抛出，用于终止当前 handler 执行。
    """
    if prompt is not None:
        await matcher.send(prompt, **kwargs)

    # ① resolve_reject：将当前 handler 塞回队列头部，下次继续执行它
    handler = current_handler.get()
    matcher.remain_handlers.insert(0, handler)
    if REJECT_CACHE_TARGET in matcher.state:
        matcher.state[REJECT_TARGET] = matcher.state[REJECT_CACHE_TARGET]

    await _create_temp_matcher(matcher, rule)
    raise FinishedException


async def enter_prompt_loop(
    matcher: "Matcher",
    handlers: list[Any],
    rule: Rule,
    prompt: "T_Message | None" = None,
    **kwargs: Any,
) -> None:
    """发送 prompt 并创建带自定义 Rule 的临时 Matcher 进入选择循环。

    与 ``reject_with_rule`` 不同，本函数 **不** 将当前 handler
    插回队列，而是使用调用者提供的 ``handlers`` 列表。
    适用于首次进入 prompt 循环（替代 ``matcher.got``）。

    Args:
        matcher: 当前 Matcher 实例。
        handlers: 临时 Matcher 执行的 handler 列表（普通函数即可）。
        rule: 临时 Matcher 使用的匹配规则。
        prompt: 发送给用户的提示消息。
        **kwargs: 传递给 ``Matcher.send()`` 的额外参数。

    Raises:
        FinishedException: 始终抛出，用于终止当前 handler 执行。
    """
    if prompt is not None:
        await matcher.send(prompt, **kwargs)

    await _create_temp_matcher(matcher, rule, handlers=handlers)
    raise FinishedException


async def _create_temp_matcher(
    matcher: "Matcher",
    rule: Rule,
    *,
    handlers: list[Any] | None = None,
) -> None:
    """创建带自定义 Rule 的临时 Matcher（内部工具函数）。"""
    bot = current_bot.get()
    event = current_event.get()
    permission = await matcher.update_permission(bot, event)

    matcher.__class__.new(
        "message",
        rule,
        permission,
        handlers if handlers is not None else matcher.remain_handlers,
        temp=True,
        priority=0,
        block=True,
        source=matcher.__class__._source,
        expire_time=bot.config.session_expire_timeout,
        default_state=matcher.state,
        default_type_updater=matcher.__class__._default_type_updater,
        default_permission_updater=matcher.__class__._default_permission_updater,
    )
