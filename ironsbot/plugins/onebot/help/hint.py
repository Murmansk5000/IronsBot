# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    Bot,
    GroupMessageEvent,
    MessageSegment,
    NoticeEvent,
    PokeNotifyEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.context import command_context, mentions_bot
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.help_hint import (
    OneBotHelpHintPort,
    is_onebot_poke_at_bot,
)
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import bot_mention

__plugin_meta__ = PluginMetadata(
    name="戳一戳提示",
    description="机器人被戳一戳时按会话权限给出可用指令提示。",
    usage="由机器人戳一戳事件触发，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService


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


def _should_offer_non_ai_group_hint(
    commands: CommandCatalog,
    features: FeatureService,
    event: GroupMessageEvent,
) -> bool:
    context = message_input_context(event)
    return (
        mentions_bot(event)
        and not features.is_message_blocked(
            context.message.actor,
            context.message.conversation,
        )
        and not event_is_feature_allowed(features, event, "ai_chat")
        and not commands.recognizes_direct_input(
            command_context(event),
            event.get_plaintext().strip(),
            ignored_plugins=("ai_chat", "ai_intent"),
        )
    )


def install(
    registry: MatcherFactory,
    service: OneBotHelpHintPort,
    features: FeatureService,
    commands: CommandCatalog,
    addressed_input_hints: AddressedInputHintService,
) -> None:
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
            MessageSegment.at(event.user_id) + MessageSegment.text(f" {reply}")
        )

    matcher = registry.on_notice(
        rule=Rule(_is_poke_at_bot),
        priority=registry.priority("help_hint"),
        block=True,
    )
    matcher.append_handler(handle_poke_help)

    async def handle_addressed_input_hint(
        matcher: Matcher,
        event: GroupMessageEvent,
    ) -> None:
        context = message_input_context(event)
        if not addressed_input_hints.admit(context):
            await matcher.finish()
        await finish_event_reply(matcher, event, DIRECT_COMMAND_HELP_HINT_TEXT)

    addressed_input_matcher = registry.on_message(
        policy=CommandPolicy.exempt("unclaimed direct mention hint"),
        rule=bot_mention()
        & Rule(
            lambda event: _should_offer_non_ai_group_hint(
                commands,
                features,
                event,
            )
        ),
        priority=registry.priority("ai_chat"),
        block=True,
    )
    addressed_input_matcher.append_handler(handle_addressed_input_hint)


def plugin_contribution(
    *,
    service: OneBotHelpHintPort,
    features: FeatureService,
    commands: CommandCatalog,
    addressed_input_hints: AddressedInputHintService,
) -> PluginContribution:
    """Declare the passive poke-hint matcher and its service dependency."""

    return PluginContribution(
        id="help_hint",
        install=partial(
            install,
            service=service,
            features=features,
            commands=commands,
            addressed_input_hints=addressed_input_hints,
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.help_hint,
            features=context.resources.features,
            commands=context.resources.commands,
            addressed_input_hints=context.resources.addressed_input_hints,
        ),
    )
