# SPDX-License-Identifier: MIT
"""OneBot poke reply matcher."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,
    NoticeEvent,
    PokeNotifyEvent,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.errors import OneBotActionError
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.services.messaging.poke_reply import PokeReplyService

__plugin_meta__ = PluginMetadata(
    name="戳一戳回复",
    description="机器人被戳一戳时按会话权限给出可用指令。",
    usage="由机器人戳一戳事件触发，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def _is_poke_at_bot(event: NoticeEvent) -> bool:
    return isinstance(event, PokeNotifyEvent) and event.target_id == event.self_id


async def _group_role(bot: Bot, event: PokeNotifyEvent) -> str | None:
    if event.group_id is None:
        return None
    try:
        info = await bot.get_group_member_info(
            group_id=event.group_id,
            user_id=event.user_id,
            no_cache=True,
        )
    except OneBotActionError:  # pragma: no cover - action rejection falls back safely
        return None
    role = info.get("role")
    return str(role) if role is not None else None


def install(
    registry: MatcherFactory,
    service: PokeReplyService,
    messenger: OneBotOutboundMessenger,
) -> None:
    async def handle_poke_reply(
        bot: Bot,
        event: PokeNotifyEvent,
    ) -> None:
        context = CommandContext(
            actor=onebot_actor_ref(event.user_id),
            conversation=onebot_conversation_ref(
                event.user_id, group_id=event.group_id
            ),
        )
        await service.handle(
            context,
            partial(messenger.send_from, bot, context),
            group_role=partial(_group_role, bot, event),
        )

    matcher = registry.on_notice(
        rule=Rule(_is_poke_at_bot),
        priority=registry.priority("poke_reply"),
        block=True,
    )
    matcher.append_handler(handle_poke_reply)


def plugin_contribution(
    *, service: PokeReplyService, messenger: OneBotOutboundMessenger
) -> PluginContribution:
    return PluginContribution(
        id="poke_reply",
        install=partial(install, service=service, messenger=messenger),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.poke_reply,
            messenger=context.resources.onebot_messenger,
        ),
    )
