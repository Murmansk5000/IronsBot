# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot import get_loaded_plugins
from nonebot.adapters import Bot, Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.plugin import PluginMetadata
from nonebot.plugin.on import on_fullmatch
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.config import AppConfig, get_app_config
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.features.visibility import plugin_visible_for_event
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

if TYPE_CHECKING:
    from nonebot.plugin import Plugin

    from ironsbot.config.models.runtime import HelpConfig

DEFAULT_IGNORED_PLUGINS = [
    "发图",
    "HTTP 缓存客户端",
    "赛尔号数据",
    "赛尔号信息查询",
    "AI @ 提示拦截",
    "超级管理员优先级",
    "定时重启",
]
HELP_ENTRIES_KEY = "_help_entries"
HELP_PLUGIN_NAME = "help"
Config = AppConfig


@dataclass(frozen=True, slots=True)
class HelpEntry:
    key: str
    name: str
    description: str
    usage: str


def get_help_config() -> HelpConfig:
    return get_app_config().runtime.help


__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="按当前群/私聊权限显示可用功能",
    usage=(
        "📖 帮助 — 查看当前会话可用的功能列表，输入序号查看详细帮助\n"
        "帮助菜单会根据群号、用户 QQ、超级管理员和各插件变量自动过滤。"
    ),
    config=Config,
)

help_cmd = on_fullmatch("帮助", rule=no_reply(), priority=0, block=True)


def _plugin_module_name(plugin: "Plugin") -> str:
    return str(getattr(plugin, "module_name", "") or getattr(plugin, "name", ""))


def _plugin_key(plugin: "Plugin") -> str:
    return _plugin_module_name(plugin) or cast("PluginMetadata", plugin.metadata).name


def _ignored_plugin_names() -> set[str]:
    return {
        *DEFAULT_IGNORED_PLUGINS,
        *get_help_config().ignored_plugins,
    }


def _is_supported_adapter(bot: Bot, metadata: PluginMetadata) -> bool:
    if metadata.supported_adapters is None:
        return True
    supported_adapters = metadata.get_supported_adapters()
    if not supported_adapters:
        return False
    return any(isinstance(bot.adapter, adapter) for adapter in supported_adapters)


def _is_supported_type(metadata: PluginMetadata) -> bool:
    return metadata.type is None or metadata.type == "application"


def _entry_from_plugin(plugin: "Plugin") -> HelpEntry:
    metadata = cast("PluginMetadata", plugin.metadata)
    return HelpEntry(
        key=_plugin_key(plugin),
        name=metadata.name,
        description=metadata.description,
        usage=metadata.usage or "暂无详细帮助。",
    )


def _visible_help_entries(bot: Bot, event: Event) -> list[HelpEntry]:
    entries: list[HelpEntry] = []
    seen_names: set[str] = set()
    ignored_names = _ignored_plugin_names()

    plugins = sorted(
        get_loaded_plugins(),
        key=lambda plugin: (
            cast("PluginMetadata", plugin.metadata).name
            if plugin.metadata
            else ""
        ),
    )
    for plugin in plugins:
        metadata = plugin.metadata
        if metadata is None:
            continue
        if metadata.name in ignored_names or metadata.name in seen_names:
            continue
        if not _is_supported_type(metadata) or not _is_supported_adapter(bot, metadata):
            continue
        module_name = _plugin_module_name(plugin)
        if not plugin_visible_for_event(metadata.name, module_name, event):
            continue

        entries.append(_entry_from_plugin(plugin))
        seen_names.add(metadata.name)

    return entries


def _format_plugin_list(entries: list[HelpEntry]) -> str:
    if not entries:
        return "当前会话没有可用的功能。"

    lines = ["📖 可用功能："]
    for index, entry in enumerate(entries, start=1):
        lines.append(f"{index}. {entry.name} — {entry.description}")
    lines.append(
        "\n💬 直接发送序号查看详细帮助 · 输入 0 退出\n"
        "⚠️ 请勿 @ 机器人或回复这条消息；@ 会产生通知，回复消息机器人无法继续处理。"
    )
    return "\n".join(lines)


def _format_plugin_detail(entry: HelpEntry) -> str:
    return f"📖 {entry.name}\n\n{entry.usage}"


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


class CustomHelpPlugin:
    name = HELP_PLUGIN_NAME
    feature = "help"
    enabled = True

    async def handle(self, event: Event, context: PluginContext) -> None:
        matcher = cast("Matcher", context.matcher)
        bot = cast("Bot", context.data["bot"])
        state = cast("T_State", context.state)
        entries = _visible_help_entries(bot, event)
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
            prompt=_help_prompt_message(event, _format_plugin_list(entries)),
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
            _format_plugin_detail(entries[index - 1]),
        )

        rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
        await reject_with_rule(matcher, rule)

    return _handler
