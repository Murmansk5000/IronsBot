# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    Bot,
    MessageSegment,
    NoticeEvent,
    PokeNotifyEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.runtime.onebot_help_hint import (
    OneBotHelpHintPort,
    is_onebot_poke_at_bot,
)
from ironsbot.runtime.plugins import (
    PluginContribution,
    active_plugin_install_context,
)

__plugin_meta__ = PluginMetadata(
    name="戳一戳提示",
    description="机器人被戳一戳时按会话权限给出可用指令提示。",
    usage="由机器人戳一戳事件触发，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry


async def _is_poke_at_bot(event: NoticeEvent) -> bool:
    if not isinstance(event, PokeNotifyEvent):
        return False
    return is_onebot_poke_at_bot(event)


async def _group_role(bot: Bot, event: PokeNotifyEvent) -> str | None:
    if event.group_id is None:
        return None
    try:
        info = await bot.get_group_member_info(
            group_id=event.group_id,
            user_id=event.user_id,
            no_cache=True,
        )
    except ActionFailed:  # pragma: no cover - adapter failures fall back safely
        return None
    role = info.get("role")
    return str(role) if role is not None else None


def install(registry: MatcherRegistry, service: OneBotHelpHintPort) -> None:
    async def handle_poke_help(
        matcher: Matcher,
        bot: Bot,
        event: PokeNotifyEvent,
    ) -> None:
        if not service.can_send(event.group_id):
            await matcher.finish()

        reply = (
            service.get_poke_reply(
                group_id=event.group_id,
                user_id=event.user_id,
            )
            or service.get_default_poke_hint(
                group_id=event.group_id,
                user_id=event.user_id,
                group_role=await _group_role(bot, event),
            )
            or DIRECT_COMMAND_HELP_HINT_TEXT
        )
        if event.group_id is None:
            await matcher.finish(reply)

        await matcher.finish(
            MessageSegment.at(event.user_id)
            + MessageSegment.text(f" {reply}")
        )

    matcher = registry.on_notice(
        rule=Rule(_is_poke_at_bot),
        priority=registry.priority("help_hint"),
        block=True,
    )
    matcher.append_handler(handle_poke_help)


def plugin_contribution(*, service: OneBotHelpHintPort) -> PluginContribution:
    """Declare the passive poke-hint matcher and its service dependency."""

    return PluginContribution(
        id="help_hint",
        install=partial(install, service=service),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(service=context.resources.help_hint),
    )
