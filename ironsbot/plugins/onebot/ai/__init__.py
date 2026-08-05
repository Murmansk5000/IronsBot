from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.app.plugin_visibility import feature_help_visible
from ironsbot.core.features import Feature
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.runtime.commands import (
    CommandAccess,
    CommandCatalog,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.onebot_context import (
    build_notice_source,
    command_context,
    mentions_bot,
)
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import bot_mention
from ironsbot.services.messaging.bot_mention_block import BotMentionBlockService

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.ai.service import AiService

AI_CHAT_PROMPT_KEY = "_ai_chat_prompt"


@dataclass(frozen=True, slots=True)
class AiChatMatcherDependencies:
    features: FeatureService
    commands: CommandCatalog
    bot_mention_block_service: BotMentionBlockService


__plugin_meta__ = PluginMetadata(
    name="AI聊天",
    description="接入 OpenAI-compatible API 的自定义聊天插件。",
    usage="群聊中 @机器人后输入问题，或在私聊中直接输入问题。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def command_descriptors(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    if not enabled:
        return ()
    return (
        *commands_from_rows(
            "ai_chat",
            "群聊",
            "ai_chat",
            (
                (
                    "ai_chat.group",
                    ("@机器人 <问题>",),
                    "向 AI 聊天提问",
                    {"access": (CommandAccess(scope="group"),)},
                ),
            ),
        ),
        *commands_from_rows(
            "ai_chat",
            "私聊",
            "ai_chat",
            (
                (
                    "ai_chat.private",
                    ("<问题>",),
                    "直接向 AI 聊天提问",
                    {"access": (CommandAccess(scope="private"),)},
                ),
            ),
        ),
    )


def _is_claimed_private_command(
    commands: CommandCatalog,
    features: FeatureService,
    event: MessageEvent,
    prompt: str,
) -> bool:
    return not isinstance(event, GroupMessageEvent) and commands.claims_direct_input(
        command_context(event),
        features,
        prompt,
        ignored_plugins=("ai_chat",),
    )


def _should_guard_non_ai_group_mention(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    return (
        isinstance(event, GroupMessageEvent)
        and mentions_bot(event)
        and not event_is_feature_allowed(features, event, "ai_chat")
    )


def _build_guard_message(event: MessageEvent) -> str:
    del event
    return DIRECT_COMMAND_HELP_HINT_TEXT


def _capture_ai_prompt(
    event: MessageEvent,
    state: T_State,
    features: FeatureService,
    commands: CommandCatalog,
) -> bool:
    if (
        getattr(event, "reply", None) is not None
        or not event_is_feature_allowed(features, event, "ai_chat")
        or (isinstance(event, GroupMessageEvent) and not mentions_bot(event))
    ):
        return False

    prompt = event.get_plaintext().strip()
    if _is_claimed_private_command(commands, features, event, prompt):
        return False
    state[AI_CHAT_PROMPT_KEY] = prompt
    return True


def _capture_group_ai_prompt(
    event: GroupMessageEvent,
    state: T_State,
    features: FeatureService,
    commands: CommandCatalog,
) -> bool:
    return _capture_ai_prompt(event, state, features, commands)


def install(
    registry: MatcherRegistry,
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
        policy=CommandPolicy.command("ai_chat", help_ids=("ai_chat.private",)),
        rule=Rule(
            bind(
                _capture_ai_prompt,
                features=dependencies.features,
                commands=dependencies.commands,
            )
        ),
        priority=registry.priority("ai_chat"),
        block=True,
    )
    direct_matcher.append_handler(run_ai_chat)

    group_at_matcher = registry.on_message(
        policy=CommandPolicy.command("ai_chat", help_ids=("ai_chat.group",)),
        rule=bot_mention()
        & Rule(
            bind(
                _capture_group_ai_prompt,
                features=dependencies.features,
                commands=dependencies.commands,
            )
        ),
        priority=registry.pre_command_priority("ai_group_at"),
        block=True,
    )
    group_at_matcher.append_handler(run_ai_chat)

    async def handle_non_ai_group_at_bot(
        matcher: Matcher,
        event: GroupMessageEvent,
    ) -> None:
        decision = dependencies.bot_mention_block_service.admit(
            message_input_context(event).message.actor
        )
        if decision.allowed:
            message = _build_guard_message(event)
        elif decision.feedback is not None:
            message = decision.feedback
        else:
            raise FinishedException
        await finish_event_reply(matcher, event, message)

    bot_mention_block_matcher = registry.on_message(
        policy=CommandPolicy.exempt("non-AI direct mention guard"),
        rule=bot_mention()
        & Rule(
            lambda event: _should_guard_non_ai_group_mention(
                dependencies.features,
                event,
            )
        ),
        priority=registry.pre_command_priority("bot_mention_block"),
        block=True,
    )
    bot_mention_block_matcher.append_handler(handle_non_ai_group_at_bot)


def plugin_contribution(
    *,
    settings: Settings,
    service: AiService,
    features: FeatureService,
    commands: CommandCatalog,
) -> PluginContribution:
    """Declare AI-chat command visibility and OneBot matcher ownership."""

    enabled = bool(settings.ai.api_key.strip())
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
        commands=command_descriptors(enabled=enabled),
        install=(
            partial(
                install,
                service=service,
                dependencies=AiChatMatcherDependencies(
                    features=features,
                    commands=commands,
                    bot_mention_block_service=BotMentionBlockService(
                        settings.messaging.command_cooldown
                    ),
                ),
            )
            if enabled
            else None
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            settings=context.settings,
            service=context.resources.ai,
            features=context.resources.features,
            commands=context.resources.commands,
        ),
    )
