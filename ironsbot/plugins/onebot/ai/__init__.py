from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.context import (
    build_notice_source,
    command_context,
)
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory, bind
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import finish_event_reply, send_event_reply
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.help_visibility import feature_help_visible

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters.onebot.v11 import Bot, MessageEvent

    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.ai.service import AiService

AI_CHAT_PROMPT_KEY = "_ai_chat_prompt"


@dataclass(frozen=True, slots=True)
class AiChatMatcherDependencies:
    input_routing: AiInputRoutingService


__plugin_meta__ = PluginMetadata(
    name="AI聊天",
    description="接入 OpenAI-compatible API 的自定义聊天插件。",
    usage="群聊中 @机器人后输入问题，或在私聊中直接输入问题。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def _capture_ai_prompt(
    event: MessageEvent,
    state: T_State,
    input_routing: AiInputRoutingService,
) -> bool:
    context = message_input_context(event)
    if not input_routing.decide(context, command_context(event)).try_chat:
        return False

    state[AI_CHAT_PROMPT_KEY] = context.text.strip()
    return True


def install(
    registry: MatcherFactory,
    service: AiService,
    dependencies: AiChatMatcherDependencies,
) -> None:
    async def run_ai_chat(
        matcher: Matcher,
        bot: Bot,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        prompt = state.get(AI_CHAT_PROMPT_KEY, "").strip()
        if not prompt:
            await finish_event_reply(
                matcher,
                event,
                "你想聊什么？可以 @我 后面直接写问题。",
            )

        if service.waiting_notice:
            await send_event_reply(matcher, event, "处理中...")

        message = message_input_context(event).message
        reply = await service.chat_reply(
            actor=message.actor,
            conversation=message.conversation,
            prompt=prompt,
            source_context=await build_notice_source(
                event,
                prompt,
                bot=bot,
            ),
        )
        if reply is None:
            raise FinishedException
        await finish_event_reply(matcher, event, reply)

    direct_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "ai_chat",
            help_ids=("ai_chat.group", "ai_chat.private"),
        ),
        rule=Rule(
            bind(
                _capture_ai_prompt,
                input_routing=dependencies.input_routing,
            )
        ),
        priority=registry.priority("ai_chat"),
        block=True,
    )
    direct_matcher.append_handler(run_ai_chat)


def plugin_contribution(
    *,
    settings: Settings,
    service: AiService,
    features: FeatureService,
    input_routing: AiInputRoutingService,
    startup_check: Callable[[], Awaitable[None]],
) -> PluginContribution:
    """Declare AI-chat command visibility and OneBot matcher ownership."""

    enabled = settings.ai.enabled
    return PluginContribution(
        id="ai_chat",
        features=frozenset({Feature.AI_CHAT, Feature.ADMIN_NOTICE}),
        help=HelpEntry(
            name="AI聊天",
            description="接入 OpenAI-compatible API 的自定义聊天插件",
            group="ai",
            order=10,
            visible=partial(
                feature_help_visible,
                features=features,
                feature="ai_chat",
                enabled=enabled,
            ),
        ),
        commands=ai_chat_command_contracts(enabled=enabled),
        install=(
            partial(
                install,
                service=service,
                dependencies=AiChatMatcherDependencies(
                    input_routing=input_routing,
                ),
            )
        ),
        hooks=(
            PluginHooks(
                first_bot_connect=(("ai_api_check", lambda _bot: startup_check()),)
            )
            if enabled
            else PluginHooks()
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            settings=context.settings,
            service=context.resources.ai,
            features=context.resources.features,
            input_routing=context.resources.ai_input_routing,
            startup_check=context.resources.ai_startup_check,
        ),
    )
