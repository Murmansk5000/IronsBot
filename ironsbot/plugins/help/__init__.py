# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import cast

from nonebot.adapters import Bot, Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.plugin import PluginMetadata
from nonebot.plugin.on import on_fullmatch
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.config.models.app import AppConfig
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.messaging.replies import event_sender_at_user_ids
from ironsbot.shared.messaging.text import build_message
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.matcher import (
    enter_prompt_loop,
    prompt_session_manager,
    reject_with_rule,
)
from ironsbot.utils.rule import no_reply

from .menu import (
    HELP_ENTRIES_KEY,
    HELP_PLUGIN_NAME,
    format_plugin_detail,
    format_plugin_list,
    visible_help_entries,
)

__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="按当前群/私聊权限显示可用功能",
    usage=(
        "📖 帮助 — 查看当前会话可用的功能列表，输入序号查看详细帮助\n"
        "帮助菜单会根据群号、用户 QQ、超级管理员和各插件变量自动过滤。"
    ),
    config=AppConfig,
)

help_cmd = on_fullmatch(
    "帮助",
    rule=no_reply(),
    priority=get_matcher_priority("help", 0),
    block=True,
)


def _help_prompt_message(event: Event, text: str):
    if not isinstance(event, MessageEvent):
        return text
    return build_message(text, at_user_ids=event_sender_at_user_ids(event))


async def _finish_help_reply(
    matcher: Matcher,
    event: Event,
    message: str,
) -> None:
    if isinstance(event, MessageEvent):
        await finish_event_reply(matcher, event, message)
        return
    await matcher.finish(message)


async def _send_help_reply(
    matcher: Matcher,
    event: Event,
    message: str,
) -> None:
    if isinstance(event, MessageEvent):
        await send_event_reply(matcher, event, message)
        return
    await matcher.send(message)


def _is_digit_input(event: Event) -> bool:
    if getattr(event, "reply", None) is not None:
        return False
    return event.get_plaintext().strip().isdigit()


class CustomHelpPlugin:
    name = HELP_PLUGIN_NAME
    feature = "help"
    enabled = True

    async def handle(self, event: Event, context: PluginContext) -> None:
        matcher = cast("Matcher", context.matcher)
        bot = cast("Bot", context.data["bot"])
        state = cast("T_State", context.state)
        entries = visible_help_entries(bot, event)
        if not entries:
            await _finish_help_reply(matcher, event, "当前会话没有可用的功能。")

        state[HELP_ENTRIES_KEY] = entries
        session_id = event.get_session_id()
        version = prompt_session_manager.acquire(session_id)
        rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
        handler = _create_selection_handler(session_id, version)

        await enter_prompt_loop(
            matcher,
            handlers=[handler],
            rule=rule,
            prompt=_help_prompt_message(event, format_plugin_list(entries)),
        )


register_plugin(CustomHelpPlugin())


@help_cmd.handle()
async def handle_help(
    bot: Bot,
    matcher: Matcher,
    event: Event,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=HELP_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        bot=bot,
    )


def _create_selection_handler(
    session_id: str,
    version: int,
) -> object:
    async def _handler(
        matcher: Matcher,
        event: Event,
        state: T_State,
    ) -> None:
        entries = state.get(HELP_ENTRIES_KEY)
        if not entries:
            raise FinishedException

        key_text = event.get_plaintext().strip()
        if key_text == "0":
            await _finish_help_reply(matcher, event, "✅ 已退出帮助。")

        if not key_text.isdigit():
            raise FinishedException

        index = int(key_text)
        if index < 1 or index > len(entries):
            await _finish_help_reply(matcher, event, "⚠️ 序号超出范围，已退出帮助。")

        await _send_help_reply(
            matcher,
            event,
            format_plugin_detail(entries[index - 1], event),
        )

        rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
        await reject_with_rule(matcher, rule)

    return _handler
