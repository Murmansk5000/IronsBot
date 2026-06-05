# SPDX-License-Identifier: MIT
"""帮助插件

通过读取插件元信息生成帮助信息，支持多轮对话选择。
"""

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.plugin.on import on_fullmatch
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    build_message,
    event_sender_at_user_ids,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.utils.matcher import (
    enter_prompt_loop,
    prompt_session_manager,
    reject_with_rule,
)
from ironsbot.utils.rule import no_reply

from .config import Config
from .data_source import (
    format_plugin_list,
    get_plugin_help_by_index,
    get_supported_plugins,
)

__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="获取插件帮助信息",
    usage=(
        "📖 帮助 — 查看插件列表，输入序号查看详细帮助\n"
        "📖 帮助 <插件名> — 直接查看指定插件的帮助"
    ),
    config=Config,
)

help_cmd = on_fullmatch("帮助", rule=no_reply(), priority=1, block=True)

_HELP_PROMPT_KEY = "_help_prompt_plugin_count"


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
    return event.get_plaintext().strip().isdigit()


@help_cmd.handle()
async def handle_help(
    bot: Bot,
    matcher: Matcher,
    event: Event,
    state: T_State,
) -> None:
    plugins = get_supported_plugins(bot)
    if not plugins:
        await _finish_help_reply(matcher, event, "当前没有可用的插件。")

    state[_HELP_PROMPT_KEY] = len(plugins)
    session_id = event.get_session_id()
    version = prompt_session_manager.acquire(session_id)
    rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)

    handler = _create_selection_handler(session_id, version)

    await enter_prompt_loop(
        matcher,
        handlers=[handler],
        rule=rule,
        prompt=_help_prompt_message(event, format_plugin_list(bot)),
    )


def _create_selection_handler(
    session_id: str,
    version: int,
) -> object:
    async def _handler(
        bot: Bot,
        matcher: Matcher,
        event: Event,
        state: T_State,
    ) -> None:
        if _HELP_PROMPT_KEY not in state:
            raise FinishedException

        key_text = event.get_plaintext().strip()

        if key_text == "0":
            await _finish_help_reply(matcher, event, "❌ 已退出帮助")

        if not key_text.isdigit():
            raise FinishedException

        index = int(key_text)
        plugin_count = state[_HELP_PROMPT_KEY]

        if index < 1 or index > plugin_count:
            await _finish_help_reply(matcher, event, "⚠️ 序号超出范围，已退出帮助")

        help_text = get_plugin_help_by_index(bot, index)
        if help_text:
            await _send_help_reply(matcher, event, help_text)
        else:
            await _send_help_reply(matcher, event, "⚠️ 未能获取该插件的帮助信息")

        rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
        await reject_with_rule(matcher, rule)

    return _handler
