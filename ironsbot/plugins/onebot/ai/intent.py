from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,  # noqa: TC002 - NoneBot resolves it at runtime
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.app.plugin_visibility import feature_help_visible
from ironsbot.core.features import Feature
from ironsbot.runtime.commands import CommandDescriptor
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.onebot_context import build_notice_source
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import natural_language

from .team_actions import run_team_action

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.core.promotions import PromotionCatalog
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.team.resource import TeamResourceService

ACTION_KEY = "_ai_intent_action"
ACTION_SOURCE_CONTEXT_KEY = "_ai_intent_source_context"

__plugin_meta__ = PluginMetadata(
    name="AI意图分析",
    description="按配置识别简短意图，并触发对应回复或功能。",
    usage="发送已配置关键词触发相应意图动作。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


@dataclass(frozen=True, slots=True)
class AiIntentDependencies:
    """OneBot dependencies needed by the configured AI action adapter."""

    service: AiService
    promotions: PromotionCatalog
    team_resource: TeamResourceService


def command_descriptors(config: Settings) -> tuple[CommandDescriptor, ...]:
    if not config.ai.api_key.strip() or not config.ai.intent_actions_enabled:
        return ()
    return tuple(
        CommandDescriptor(
            id=f"ai_intent.{action_id}",
            plugin_id="ai_intent",
            section="关键词意图",
            examples=tuple(action.keywords),
            description="机器人识别到相应意图后自动回复",
            features_any=(action.feature,),
            interaction="automatic",
        )
        for action_id, action in config.ai.intent_actions.items()
        if action.enabled and action.keywords
    )


async def _handle_ai_reply_action(
    service: AiService,
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
    source_context: str | None,
) -> None:
    reply = await service.run_reply_action(
        action,
        event.get_plaintext(),
        source_context=source_context,
    )
    if reply is None:
        return

    await finish_event_reply(
        matcher,
        event,
        reply,
    )


def _resolve_action_command_id(
    _event: MessageEvent,
    state: T_State,
) -> str:
    action = state.get(ACTION_KEY)
    action_id = str(getattr(action, "id", "")).strip()
    return f"ai_intent.{action_id}" if action_id else "ai_intent"


def install(
    registry: MatcherRegistry,
    dependencies: AiIntentDependencies,
    command_help_ids: tuple[str, ...],
) -> None:
    if not command_help_ids:
        return

    async def match_action(
        bot: Bot,
        event: MessageEvent,
        state: T_State,
    ) -> bool:
        text = event.get_plaintext().strip()
        message = message_input_context(event).message
        source_context = await build_notice_source(
            event,
            text,
            bot=bot,
        )
        action = await dependencies.service.classify_intent(
            text,
            actor=message.actor,
            conversation=message.conversation,
            source_context=source_context,
        )
        if action is None:
            return False
        state[ACTION_KEY] = action
        state[ACTION_SOURCE_CONTEXT_KEY] = source_context
        return True

    async def handle_action(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        action = state[ACTION_KEY]
        if dependencies.service.is_team_action(action):
            await run_team_action(
                matcher,
                event,
                action,
                dependencies.team_resource,
            )
            return
        if action.action == "ai_reply":
            await _handle_ai_reply_action(
                dependencies.service,
                action,
                matcher,
                event,
                str(state.get(ACTION_SOURCE_CONTEXT_KEY, "") or "") or None,
            )
            return
        if action.action == "promotion":
            await finish_event_reply(
                matcher,
                event,
                dependencies.promotions.require(action.promotion).message,
            )
            return
        await finish_event_reply(
            matcher,
            event,
            action.message,
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            _resolve_action_command_id,
            help_ids=command_help_ids,
        ),
        rule=Rule(match_action) & natural_language(),
        priority=registry.priority("ai_intent"),
        block=True,
    )
    matcher.append_handler(handle_action)


def plugin_contribution(
    *,
    settings: Settings,
    service: AiService,
    features: FeatureService,
    promotions: PromotionCatalog,
    team_resource: TeamResourceService,
) -> PluginContribution:
    """Declare configured intent actions and their natural-language matcher."""

    enabled = bool(settings.ai.api_key.strip()) and settings.ai.intent_actions_enabled
    commands = command_descriptors(settings)
    return PluginContribution(
        id="ai_intent",
        features=frozenset(
            {
                Feature.AI_INTENT,
                Feature.AI_INTENT_TEAM_RECOMMEND,
                Feature.AI_INTENT_FIRE_MANUAL,
            }
        ),
        help=HelpEntry(
            name="AI意图分析",
            description="按配置识别简短意图，并触发对应回复或功能。",
            group="ai",
            order=20,
            visible=partial(
                feature_help_visible,
                features=features,
                feature="ai_intent",
                enabled=enabled,
            ),
        ),
        commands=commands,
        install=partial(
            install,
            dependencies=AiIntentDependencies(
                service=service,
                promotions=promotions,
                team_resource=team_resource,
            ),
            command_help_ids=tuple(command.id for command in commands),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            settings=context.settings,
            service=context.resources.ai,
            features=context.resources.features,
            promotions=context.resources.promotions,
            team_resource=context.resources.team_resource,
        ),
    )
